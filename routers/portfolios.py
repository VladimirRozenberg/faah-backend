"""Routes FastAPI utilisées pour gérer les portefeuilles."""

from fastapi import APIRouter, HTTPException, status

from db import DbSession
from portfolio.repository import (
    AmbiguousPortfolioError,
    buy_asset,
    create_user_portfolio,
    list_user_portfolios,
    read_transactions,
    read_user_portfolio,
    sell_asset,
)
from portfolio.schemas import (
    BuyAssetRequest,
    PortfolioCreateRequest,
    PortfolioListResponse,
    PortfolioResponse,
    SellAssetRequest,
    TransactionListResponse,
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


@router.get(
    "/users/{user_id}/portfolios",
    response_model=PortfolioListResponse,
)
async def get_user_portfolios(
    user_id: int,
    db: DbSession,
) -> PortfolioListResponse:
    """Return all portfolios owned by the user."""

    try:
        return await list_user_portfolios(db, user_id)
    except LookupError as error:
        raise create_http_error(error) from error


@router.post(
    "/users/{user_id}/portfolio/create",
    response_model=PortfolioResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_portfolio(
    user_id: int,
    data: PortfolioCreateRequest,
    db: DbSession,
) -> PortfolioResponse:
    """Create another portfolio and its dedicated strategist."""

    try:
        return await create_user_portfolio(db, user_id, data)
    except (LookupError, ValueError) as error:
        raise create_http_error(error) from error


@router.get(
    "/users/{user_id}/portfolios/{portfolio_id}",
    response_model=PortfolioResponse,
)
async def get_portfolio(
    user_id: int,
    portfolio_id: int,
    db: DbSession,
) -> PortfolioResponse:
    """Return one portfolio after verifying ownership."""

    try:
        return await read_user_portfolio(db, user_id, portfolio_id)
    except LookupError as error:
        raise create_http_error(error) from error


@router.post(
    "/users/{user_id}/portfolios/{portfolio_id}/assets/buy",
    response_model=PortfolioResponse,
)
async def buy_portfolio_asset_by_id(
    user_id: int,
    portfolio_id: int,
    data: BuyAssetRequest,
    db: DbSession,
) -> PortfolioResponse:
    """Add a simulated purchase to a selected owned portfolio."""

    try:
        return await buy_asset(db, user_id, data, portfolio_id)
    except (LookupError, ValueError) as error:
        raise create_http_error(error) from error


@router.post(
    "/users/{user_id}/portfolios/{portfolio_id}/assets/sell",
    response_model=PortfolioResponse,
)
async def sell_portfolio_asset_by_id(
    user_id: int,
    portfolio_id: int,
    data: SellAssetRequest,
    db: DbSession,
) -> PortfolioResponse:
    """Sell from a selected owned portfolio."""

    try:
        return await sell_asset(db, user_id, data, portfolio_id)
    except (LookupError, ValueError) as error:
        raise create_http_error(error) from error


@router.get(
    "/users/{user_id}/portfolios/{portfolio_id}/transactions",
    response_model=TransactionListResponse,
)
async def get_portfolio_transactions_by_id(
    user_id: int,
    portfolio_id: int,
    db: DbSession,
) -> TransactionListResponse:
    """Return transaction history for a selected owned portfolio."""

    try:
        return await read_transactions(db, user_id, portfolio_id)
    except LookupError as error:
        raise create_http_error(error) from error


@router.get(
    "/users/{user_id}/portfolio",
    response_model=PortfolioResponse,
)
async def get_user_portfolio(
    user_id: int,
    db: DbSession,
) -> PortfolioResponse:
    """Legacy route; valid only while the user has at most one portfolio."""

    try:
        return await read_user_portfolio(db, user_id)
    except (LookupError, AmbiguousPortfolioError) as error:
        raise create_http_error(error) from error


@router.post(
    "/users/{user_id}/portfolio/assets/buy",
    response_model=PortfolioResponse,
)
async def buy_portfolio_asset(
    user_id: int,
    data: BuyAssetRequest,
    db: DbSession,
) -> PortfolioResponse:
    """Ajoute un achat simulé dans le portefeuille."""

    try:
        return await buy_asset(db, user_id, data)
    except (LookupError, ValueError) as error:
        raise create_http_error(error) from error


@router.post(
    "/users/{user_id}/portfolio/assets/sell",
    response_model=PortfolioResponse,
)
async def sell_portfolio_asset(
    user_id: int,
    data: SellAssetRequest,
    db: DbSession,
) -> PortfolioResponse:
    """Retire une quantité d'un actif du portefeuille."""

    try:
        return await sell_asset(db, user_id, data)
    except (LookupError, ValueError) as error:
        raise create_http_error(error) from error


@router.get(
    "/users/{user_id}/portfolio/transactions",
    response_model=TransactionListResponse,
)
async def get_portfolio_transactions(
    user_id: int,
    db: DbSession,
) -> TransactionListResponse:
    """Retourne l'historique des achats et des ventes."""

    try:
        return await read_transactions(db, user_id)
    except (LookupError, AmbiguousPortfolioError) as error:
        raise create_http_error(error) from error
