"""Routes FastAPI utilisées pour gérer les portefeuilles."""

from fastapi import APIRouter, HTTPException

from db import DbSession
from portfolio.repository import (
    buy_asset,
    read_transactions,
    read_user_portfolio,
    sell_asset,
)
from portfolio.schemas import (
    BuyAssetRequest,
    PortfolioResponse,
    SellAssetRequest,
    TransactionListResponse,
)


router = APIRouter(prefix="/api", tags=["Portefeuilles"])


def create_http_error(error: Exception) -> HTTPException:
    """Prépare une erreur HTTP compréhensible."""

    status_code = 404 if isinstance(error, LookupError) else 400
    return HTTPException(
        status_code=status_code,
        detail=str(error),
    )


@router.get(
    "/users/{user_id}/portfolio",
    response_model=PortfolioResponse,
)
async def get_user_portfolio(
    user_id: int,
    db: DbSession,
) -> PortfolioResponse:
    """Retourne le portefeuille unique, même s'il est vide."""

    try:
        return await read_user_portfolio(db, user_id)
    except LookupError as error:
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
    except LookupError as error:
        raise create_http_error(error) from error
