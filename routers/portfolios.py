"""Routes FastAPI utilisées pour gérer les portefeuilles."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from auth.login import CurrentUser
from db import DbSession
from models import (
    Portfolio,
    PortfolioRecommendation,
    PortfolioStrategist,
    PortfolioStrategistRun,
)
from portfolio.repository import (
    AmbiguousPortfolioError,
    buy_asset,
    create_user_portfolio,
    get_active_account,
    list_user_portfolios,
    read_transactions,
    read_user_available_cash,
    read_user_asset_value,
    read_user_portfolio,
    read_user_transactions,
    sell_asset,
    update_user_portfolio,
)
from portfolio.schemas import (
    BuyAssetRequest,
    PortfolioCreateRequest,
    PortfolioResponse,
    PortfolioSummaryListResponse,
    PortfolioUpdateRequest,
    SellAssetRequest,
    TransactionListResponse,
    UserAvailableCashResponse,
    UserAssetValueResponse,
    UserTransactionListResponse,
)
from portfolio_strategist.repository import (
    StrategistRepository,
    database_hours_ago,
)
from portfolio_strategist.schemas import (
    PortfolioRecommendationResponse,
    PortfolioStrategistResponse,
    QueueStrategistReviewResponse,
    StrategistReviewListResponse,
    StrategistReviewResponse,
    PortfolioRecommendationPageResponse,
    UserRecommendationPageResponse,
    UserRecommendationResponse,
)


router = APIRouter(prefix="/api", tags=["Portefeuilles"])


# Les routes reçoivent la demande et appellent portfolio.repository.
# Les calculs et les écritures restent dans ce dossier pour éviter les doublons.
# DbSession fournit la session de base de données pour la demande en cours.


def create_http_error(error: Exception) -> HTTPException:
    """Prépare une erreur HTTP compréhensible."""

    # 404 : utilisateur, actif ou position introuvable.
    # 400 : opération refusée, par exemple une vente trop importante.
    status_code = 400
    if isinstance(error, AmbiguousPortfolioError):
        status_code = 409
    elif isinstance(error, LookupError):
        status_code = 404
    return HTTPException(
        status_code=status_code,
        detail=str(error),
    )


async def _owned_strategist(
    db: DbSession,
    user_id: int,
    portfolio_id: int,
    *,
    lock: bool = False,
) -> PortfolioStrategist:
    statement = (
        select(PortfolioStrategist)
        .join(Portfolio, Portfolio.prt_id == PortfolioStrategist.pst_prt_id)
        .where(
            Portfolio.prt_id == portfolio_id,
            Portfolio.prt_usr_id == user_id,
        )
    )
    if lock:
        statement = statement.with_for_update()
    strategist = await db.scalar(statement)
    if strategist is None:
        raise HTTPException(
            status_code=404,
            detail=f"Portfolio {portfolio_id} or its strategist was not found for user {user_id}",
        )
    return strategist


def _recommendation_response(
    item: PortfolioRecommendation,
) -> PortfolioRecommendationResponse:
    return PortfolioRecommendationResponse(
        recommendation_id=item.prc_id,
        run_id=item.prc_psr_id,
        kind=item.prc_kind,
        asset_id=item.prc_ast_id,
        asset_symbol=item.prc_asset_symbol,
        signal_id=item.prc_sig_id,
        action=item.prc_action,
        reason=item.prc_reason,
        confidence=item.prc_confidence,
        status=item.prc_status,
        created_at=item.prc_created_at,
        updated_at=item.prc_updated_at,
    )


def _review_response(
    run: PortfolioStrategistRun,
    recommendations: list[PortfolioRecommendation],
) -> StrategistReviewResponse:
    return StrategistReviewResponse(
        run_id=run.psr_id,
        review_type=run.psr_review_type,
        status=run.psr_status,
        priority=run.psr_priority,
        asset_id=run.psr_ast_id,
        signal_id=run.psr_sig_id,
        market_event_id=run.psr_moe_id,
        result_analysis_id=run.psr_result_anl_id,
        reason=run.psr_reason,
        decision=run.psr_decision,
        error=run.psr_error,
        recommendations=[_recommendation_response(item) for item in recommendations],
        created_at=run.psr_created_at,
        started_at=run.psr_started_at,
        completed_at=run.psr_completed_at,
    )


async def _recommendations_by_run(
    db: DbSession,
    run_ids: list[int],
) -> dict[int, list[PortfolioRecommendation]]:
    result = {run_id: [] for run_id in run_ids}
    if not run_ids:
        return result
    recommendations = list(
        (
            await db.scalars(
                select(PortfolioRecommendation)
                .where(PortfolioRecommendation.prc_psr_id.in_(run_ids))
                .order_by(PortfolioRecommendation.prc_created_at)
            )
        ).all()
    )
    for recommendation in recommendations:
        result[recommendation.prc_psr_id].append(recommendation)
    return result


@router.get(
    "/users/me/portfolios",
    response_model=PortfolioSummaryListResponse,
)
async def get_user_portfolios(
    user: CurrentUser,
    db: DbSession,
) -> PortfolioSummaryListResponse:
    """Return all portfolios owned by the user."""

    user_id = user.user_id

    try:
        return await list_user_portfolios(db, user_id)
    except LookupError as error:
        raise create_http_error(error) from error



@router.get(
    "/users/me/available-cash",
    response_model=UserAvailableCashResponse,
)
async def get_user_available_cash(
    user: CurrentUser,
    db: DbSession,
) -> UserAvailableCashResponse:
    """Return the available simulated USD cash for one user."""

    user_id = user.user_id

    try:
        return await read_user_available_cash(db, user_id)
    except LookupError as error:
        raise create_http_error(error) from error


@router.get(
    "/users/me/asset-value",
    response_model=UserAssetValueResponse,
)
async def get_user_asset_value(
    user: CurrentUser,
    db: DbSession,
) -> UserAssetValueResponse:
    """Return the USD value of active holdings across all user portfolios."""

    user_id = user.user_id

    try:
        return await read_user_asset_value(db, user_id)
    except LookupError as error:
        raise create_http_error(error) from error



@router.get(
    "/users/me/recommendations",
    response_model=UserRecommendationPageResponse,
)
async def get_user_recommendations(
    user: CurrentUser,
    db: DbSession,
    within: Literal["1h"] | None = Query(default=None),
    kind: Literal[
        "opportunity",
        "holding_assessment",
        "targeted_conclusion",
    ] | None = Query(default=None),
    status_filter: Literal["new", "viewed", "dismissed", "acted_on"] | None = Query(
        default=None,
        alias="status",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> UserRecommendationPageResponse:
    """Return a filtered page of recommendations across the user's portfolios."""

    user_id = user.user_id

    try:
        await get_active_account(db, user_id)
    except LookupError as error:
        raise create_http_error(error) from error

    filters = [Portfolio.prt_usr_id == user_id]
    if within == "1h":
        filters.append(
            PortfolioRecommendation.prc_created_at >= database_hours_ago(db, 1)
        )
    if kind is not None:
        filters.append(PortfolioRecommendation.prc_kind == kind)
    if status_filter is not None:
        filters.append(PortfolioRecommendation.prc_status == status_filter)

    count = await db.scalar(
        select(func.count(PortfolioRecommendation.prc_id))
        .join(Portfolio, Portfolio.prt_id == PortfolioRecommendation.prc_prt_id)
        .where(*filters)
    )
    rows = (
        await db.execute(
            select(PortfolioRecommendation, Portfolio)
            .join(Portfolio, Portfolio.prt_id == PortfolioRecommendation.prc_prt_id)
            .where(*filters)
            .order_by(
                PortfolioRecommendation.prc_created_at.desc(),
                PortfolioRecommendation.prc_id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    items = [
        UserRecommendationResponse(
            recommendation_id=recommendation.prc_id,
            portfolio_id=portfolio.prt_id,
            portfolio_name=portfolio.prt_name,
            run_id=recommendation.prc_psr_id,
            kind=recommendation.prc_kind,
            asset_id=recommendation.prc_ast_id,
            asset_symbol=recommendation.prc_asset_symbol,
            signal_id=recommendation.prc_sig_id,
            action=recommendation.prc_action,
            reason=recommendation.prc_reason,
            confidence=recommendation.prc_confidence,
            status=recommendation.prc_status,
            created_at=recommendation.prc_created_at,
            updated_at=recommendation.prc_updated_at,
        )
        for recommendation, portfolio in rows
    ]
    return UserRecommendationPageResponse(
        count=count or 0,
        page=page,
        page_size=page_size,
        items=items,
    )


@router.get(
    "/users/me/portfolios/{portfolio_id}/recommendations",
    response_model=PortfolioRecommendationPageResponse,
)
async def get_portfolio_recommendations(
    user: CurrentUser,
    portfolio_id: int,
    db: DbSession,
    within: Literal["1h"] | None = Query(default=None),
    kind: Literal[
        "opportunity",
        "holding_assessment",
        "targeted_conclusion",
    ] | None = Query(default=None),
    status_filter: Literal["new", "viewed", "dismissed", "acted_on"] | None = Query(
        default=None,
        alias="status",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PortfolioRecommendationPageResponse:
    """Return a page of recommendations belonging to one owned portfolio."""

    user_id = user.user_id

    try:
        await get_active_account(db, user_id)
    except LookupError as error:
        raise create_http_error(error) from error

    owned_portfolio_id = await db.scalar(
        select(Portfolio.prt_id).where(
            Portfolio.prt_id == portfolio_id,
            Portfolio.prt_usr_id == user_id,
        )
    )
    if owned_portfolio_id is None:
        raise HTTPException(status_code=404, detail="Portfolio not found for user.")

    filters = [PortfolioRecommendation.prc_prt_id == portfolio_id]
    if within == "1h":
        filters.append(
            PortfolioRecommendation.prc_created_at >= database_hours_ago(db, 1)
        )
    if kind is not None:
        filters.append(PortfolioRecommendation.prc_kind == kind)
    if status_filter is not None:
        filters.append(PortfolioRecommendation.prc_status == status_filter)

    count = await db.scalar(
        select(func.count(PortfolioRecommendation.prc_id)).where(*filters)
    ) or 0
    rows = list(
        (
            await db.scalars(
                select(PortfolioRecommendation)
                .where(*filters)
                .order_by(
                    PortfolioRecommendation.prc_created_at.desc(),
                    PortfolioRecommendation.prc_id.desc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return PortfolioRecommendationPageResponse(
        count=count,
        page=page,
        page_size=page_size,
        items=[
            PortfolioRecommendationResponse(
                recommendation_id=item.prc_id,
                run_id=item.prc_psr_id,
                kind=item.prc_kind,
                asset_id=item.prc_ast_id,
                asset_symbol=item.prc_asset_symbol,
                signal_id=item.prc_sig_id,
                action=item.prc_action,
                reason=item.prc_reason,
                confidence=item.prc_confidence,
                status=item.prc_status,
                created_at=item.prc_created_at,
                updated_at=item.prc_updated_at,
            )
            for item in rows
        ],
    )


@router.post(
    "/users/me/portfolio/create",
    response_model=PortfolioResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_portfolio(
    user: CurrentUser,
    data: PortfolioCreateRequest,
    db: DbSession,
) -> PortfolioResponse:
    """Create another portfolio and its dedicated strategist."""

    user_id = user.user_id

    try:
        return await create_user_portfolio(db, user_id, data)
    except (LookupError, ValueError) as error:
        raise create_http_error(error) from error


@router.patch(
    "/users/me/portfolios/{portfolio_id}",
    response_model=PortfolioResponse,
)
async def update_portfolio(
    user: CurrentUser,
    portfolio_id: int,
    data: PortfolioUpdateRequest,
    db: DbSession,
) -> PortfolioResponse:
    """Update an owned portfolio, including its active state."""

    user_id = user.user_id

    try:
        return await update_user_portfolio(db, user_id, portfolio_id, data)
    except (LookupError, ValueError) as error:
        raise create_http_error(error) from error


@router.get(
    "/users/me/portfolios/{portfolio_id}",
    response_model=PortfolioResponse,
)
async def get_portfolio(
    user: CurrentUser,
    portfolio_id: int,
    db: DbSession,
) -> PortfolioResponse:
    """Return one portfolio after verifying ownership."""

    user_id = user.user_id

    try:
        return await read_user_portfolio(db, user_id, portfolio_id)
    except LookupError as error:
        raise create_http_error(error) from error


@router.get(
    "/users/me/portfolios/{portfolio_id}/strategist",
    response_model=PortfolioStrategistResponse,
)
async def get_portfolio_strategist(
    user: CurrentUser,
    portfolio_id: int,
    db: DbSession,
) -> PortfolioStrategistResponse:
    """Return frontend-ready strategist state for an owned portfolio."""

    user_id = user.user_id

    strategist = await _owned_strategist(db, user_id, portfolio_id)
    active_run = await db.scalar(
        select(PortfolioStrategistRun)
        .where(
            PortfolioStrategistRun.psr_pst_id == strategist.pst_id,
            PortfolioStrategistRun.psr_status.in_(("pending", "running")),
        )
        .order_by(PortfolioStrategistRun.psr_created_at.desc())
        .limit(1)
    )
    latest_run = await db.scalar(
        select(PortfolioStrategistRun)
        .where(
            PortfolioStrategistRun.psr_pst_id == strategist.pst_id,
            PortfolioStrategistRun.psr_status.in_(("succeeded", "merged")),
        )
        .order_by(PortfolioStrategistRun.psr_completed_at.desc())
        .limit(1)
    )
    selected_runs = [run for run in (active_run, latest_run) if run is not None]
    recommendations = await _recommendations_by_run(
        db, list({run.psr_id for run in selected_runs})
    )
    status_counts = (
        await db.execute(
            select(
                PortfolioRecommendation.prc_status,
                func.count(PortfolioRecommendation.prc_id),
            )
            .where(PortfolioRecommendation.prc_prt_id == portfolio_id)
            .group_by(PortfolioRecommendation.prc_status)
        )
    ).all()
    return PortfolioStrategistResponse(
        strategist_id=strategist.pst_id,
        portfolio_id=portfolio_id,
        status=strategist.pst_status,
        instructions=strategist.pst_instructions,
        last_signal_id=strategist.pst_last_signal_id,
        last_full_review_at=strategist.pst_last_full_review_at,
        next_full_review_at=strategist.pst_next_full_review_at,
        last_summary=strategist.pst_last_summary,
        active_review=(
            _review_response(active_run, recommendations[active_run.psr_id])
            if active_run is not None
            else None
        ),
        latest_review=(
            _review_response(latest_run, recommendations[latest_run.psr_id])
            if latest_run is not None
            else None
        ),
        recommendation_counts={key: count for key, count in status_counts},
    )


@router.get(
    "/users/me/portfolios/{portfolio_id}/strategist/reviews",
    response_model=StrategistReviewListResponse,
)
async def get_portfolio_strategist_reviews(
    user: CurrentUser,
    portfolio_id: int,
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
) -> StrategistReviewListResponse:
    """Return strategist review history and its normalized recommendations."""

    user_id = user.user_id

    strategist = await _owned_strategist(db, user_id, portfolio_id)
    runs = list(
        (
            await db.scalars(
                select(PortfolioStrategistRun)
                .where(PortfolioStrategistRun.psr_pst_id == strategist.pst_id)
                .order_by(PortfolioStrategistRun.psr_created_at.desc())
                .limit(limit)
            )
        ).all()
    )
    recommendations = await _recommendations_by_run(db, [run.psr_id for run in runs])
    return StrategistReviewListResponse(
        count=len(runs),
        items=[_review_response(run, recommendations[run.psr_id]) for run in runs],
    )


@router.post(
    "/users/me/portfolios/{portfolio_id}/strategist/reviews",
    response_model=QueueStrategistReviewResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_portfolio_strategist_review(
    user: CurrentUser,
    portfolio_id: int,
    db: DbSession,
) -> QueueStrategistReviewResponse:
    """Queue one full review, reusing an already active full review if present."""

    user_id = user.user_id

    strategist = await _owned_strategist(db, user_id, portfolio_id, lock=True)
    active_run = await db.scalar(
        select(PortfolioStrategistRun)
        .where(
            PortfolioStrategistRun.psr_pst_id == strategist.pst_id,
            PortfolioStrategistRun.psr_review_type == "full",
            PortfolioStrategistRun.psr_status.in_(("pending", "running")),
        )
        .order_by(PortfolioStrategistRun.psr_created_at.desc())
        .limit(1)
    )
    already_queued = active_run is not None
    run = active_run or await StrategistRepository(db).queue_full_review(portfolio_id)
    return QueueStrategistReviewResponse(
        run_id=run.psr_id,
        portfolio_id=portfolio_id,
        status=run.psr_status,
        already_queued=already_queued,
        message=(
            "A full strategist review is already queued or running."
            if already_queued
            else "Full strategist review queued."
        ),
    )


@router.post(
    "/users/me/portfolios/{portfolio_id}/assets/buy",
    response_model=PortfolioResponse,
)
async def buy_portfolio_asset_by_id(
    user: CurrentUser,
    portfolio_id: int,
    data: BuyAssetRequest,
    db: DbSession,
) -> PortfolioResponse:
    """Add a simulated purchase to a selected owned portfolio."""

    user_id = user.user_id

    try:
        return await buy_asset(db, user_id, data, portfolio_id)
    except (LookupError, ValueError) as error:
        raise create_http_error(error) from error


@router.post(
    "/users/me/portfolios/{portfolio_id}/assets/sell",
    response_model=PortfolioResponse,
)
async def sell_portfolio_asset_by_id(
    user: CurrentUser,
    portfolio_id: int,
    data: SellAssetRequest,
    db: DbSession,
) -> PortfolioResponse:
    """Sell from a selected owned portfolio."""

    user_id = user.user_id

    try:
        return await sell_asset(db, user_id, data, portfolio_id)
    except (LookupError, ValueError) as error:
        raise create_http_error(error) from error


@router.get(
    "/users/me/transactions",
    response_model=UserTransactionListResponse,
)
async def get_user_transactions(
    user: CurrentUser,
    db: DbSession,
) -> UserTransactionListResponse:
    """Return every transaction across the authenticated user's portfolios."""

    try:
        return await read_user_transactions(db, user.user_id)
    except LookupError as error:
        raise create_http_error(error) from error


@router.get(
    "/users/me/portfolios/{portfolio_id}/transactions",
    response_model=TransactionListResponse,
)
async def get_portfolio_transactions_by_id(
    user: CurrentUser,
    portfolio_id: int,
    db: DbSession,
) -> TransactionListResponse:
    """Return transaction history for a selected owned portfolio."""

    user_id = user.user_id

    try:
        return await read_transactions(db, user_id, portfolio_id)
    except LookupError as error:
        raise create_http_error(error) from error


@router.get(
    "/users/me/portfolio",
    response_model=PortfolioResponse,
)
async def get_user_portfolio(
    user: CurrentUser,
    db: DbSession,
) -> PortfolioResponse:
    """Legacy route; valid only while the user has at most one portfolio."""

    user_id = user.user_id

    try:
        return await read_user_portfolio(db, user_id)
    except (LookupError, AmbiguousPortfolioError) as error:
        raise create_http_error(error) from error


@router.post(
    "/users/me/portfolio/assets/buy",
    response_model=PortfolioResponse,
)
async def buy_portfolio_asset(
    user: CurrentUser,
    data: BuyAssetRequest,
    db: DbSession,
) -> PortfolioResponse:
    """Ajoute un achat simulé dans le portefeuille."""

    user_id = user.user_id

    try:
        return await buy_asset(db, user_id, data)
    except (LookupError, ValueError) as error:
        raise create_http_error(error) from error


@router.post(
    "/users/me/portfolio/assets/sell",
    response_model=PortfolioResponse,
)
async def sell_portfolio_asset(
    user: CurrentUser,
    data: SellAssetRequest,
    db: DbSession,
) -> PortfolioResponse:
    """Retire une quantité d'un actif du portefeuille."""

    user_id = user.user_id

    try:
        return await sell_asset(db, user_id, data)
    except (LookupError, ValueError) as error:
        raise create_http_error(error) from error


@router.get(
    "/users/me/portfolio/transactions",
    response_model=TransactionListResponse,
)
async def get_portfolio_transactions(
    user: CurrentUser,
    db: DbSession,
) -> TransactionListResponse:
    """Retourne l'historique des achats et des ventes."""

    user_id = user.user_id

    try:
        return await read_transactions(db, user_id)
    except (LookupError, AmbiguousPortfolioError) as error:
        raise create_http_error(error) from error
