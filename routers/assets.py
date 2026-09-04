"""Routes HTTP liées aux actifs et à leur historique."""

import asyncio

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from assets.market_data import (
    ALLOWED_PERIOD_INTERVALS,
    InvalidHistoryRequestError,
    MarketDataUnavailableError,
    market_data_service,
)

from assets.schemas import (
    AssetItem,
    AssetListResponse,
    AssetSummary,
    CandleResponse,
    MarketListResponse,
)

from db import DbSession
from models import Asset, Crypto, Forex, Future, Stock


# Toutes les routes de ce fichier commencent par /api et sont regroupées
# sous le titre « Marché » dans la documentation Swagger.
router = APIRouter(prefix="/api", tags=["Marché"])


async def create_asset_item(
    db: AsyncSession,
    asset: Asset,
) -> AssetItem:
    """Transforme un Asset PostgreSQL en réponse complète."""

    item = AssetItem(
        id=asset.ast_id,
        symbol=asset.ast_symbol,
        name=asset.ast_name,
        type=asset.ast_type,
        yahoo_type=asset.ast_yahoo_type,
        exchange=asset.ast_exchange,
        currency=asset.ast_currency,
        country=asset.ast_country,
        is_tracked=asset.ast_is_tracked,
        created_at=asset.ast_created_at,
        updated_at=asset.ast_updated_at,
    )

    if asset.ast_type == "stock":
        stock = await db.get(Stock, asset.ast_id)

        if stock is not None:
            item.sector = stock.sto_sector
            item.industry = stock.sto_industry

    elif asset.ast_type == "crypto":
        crypto = await db.get(Crypto, asset.ast_id)

        if crypto is not None:
            item.base_currency = crypto.cry_base_currency
            item.quote_currency = crypto.cry_quote_currency
            item.blockchain = crypto.cry_blockchain
            item.contract_address = crypto.cry_contract_address

    elif asset.ast_type == "forex":
        forex = await db.get(Forex, asset.ast_id)

        if forex is not None:
            item.base_currency = forex.for_base_currency
            item.quote_currency = forex.for_quote_currency

    elif asset.ast_type == "future":
        future = await db.get(Future, asset.ast_id)

        if future is not None:
            item.underlying_name = future.fut_underlying_name
            item.underlying_type = future.fut_underlying_type
            item.unit = future.fut_unit
            item.contract_size = (
                float(future.fut_contract_size)
                if future.fut_contract_size is not None
                else None
            )

    return item


def raise_http_error(error: Exception) -> None:
    """Convertit les erreurs du service en réponses HTTP compréhensibles."""

    if isinstance(error, InvalidHistoryRequestError):
        raise HTTPException(status_code=400, detail=str(error)) from error
    if isinstance(error, MarketDataUnavailableError):
        raise HTTPException(status_code=502, detail=str(error)) from error
    raise error


@router.get("/assets", response_model=AssetListResponse)
async def list_assets(db: DbSession) -> AssetListResponse:
    """Retourne tous les actifs enregistrés dans PostgreSQL."""

    result = await db.execute(
        select(Asset).order_by(Asset.ast_type, Asset.ast_name)
    )
    database_assets = result.scalars().all()

    items = []

    for asset in database_assets:
        item = await create_asset_item(db, asset)
        items.append(item)

    return AssetListResponse(
        count=len(items),
        items=items,
    )


@router.get("/market", response_model=MarketListResponse)
async def list_market(db: DbSession) -> MarketListResponse:
    """Retourne les prix des actifs avec yfinance."""

    try:
        result = await db.execute(
            select(Asset)
            .where(Asset.ast_is_tracked.is_(True))
            .order_by(Asset.ast_type, Asset.ast_name)
        )
        database_assets = list(result.scalars().all())
        items = await asyncio.to_thread(
            market_data_service.get_assets,
            database_assets,
        )
        return MarketListResponse(
            count=len(items),
            items=items,
        )
    except Exception as error:
        raise_http_error(error)
        raise


@router.get("/assets/{symbol}", response_model=AssetItem)
async def get_asset(symbol: str, db: DbSession) -> AssetItem:
    """Recherche un actif dans PostgreSQL avec son symbole."""

    symbol = symbol.upper()

    asset = await db.scalar(
        select(Asset).where(Asset.ast_symbol == symbol)
    )

    if asset is None:
        raise HTTPException(
            status_code=404,
            detail=f"L'actif {symbol} n'existe pas.",
        )

    return await create_asset_item(db, asset)


@router.get("/assets/{symbol}/market", response_model=AssetSummary)
async def get_asset_market(symbol: str, db: DbSession) -> AssetSummary:
    """Retourne le prix et la variation d'un actif avec yfinance."""

    symbol = symbol.upper()
    asset = await db.scalar(
        select(Asset).where(Asset.ast_symbol == symbol)
    )

    if asset is None:
        raise HTTPException(status_code=404, detail=f"L'actif {symbol} n'existe pas.")

    try:
        return await asyncio.to_thread(market_data_service.get_asset, asset)
    except Exception as error:
        raise_http_error(error)
        raise


@router.get("/assets/{symbol}/candles", response_model=CandleResponse)
async def get_asset_candles(
    symbol: str,
    db: DbSession,
    period: str = Query(default="1d", description="Exemples : 1d, 5d, 1mo, 1y"),
    interval: str = Query(default="5m", description="Exemples : 1m, 5m, 1h, 1d"),
) -> CandleResponse:
    """Retourne les bougies OHLCV qui serviront au graphique Avalonia."""

    symbol = symbol.upper()
    asset = await db.scalar(
        select(Asset).where(Asset.ast_symbol == symbol)
    )

    if asset is None:
        raise HTTPException(status_code=404, detail=f"L'actif {symbol} n'existe pas.")

    try:
        return await asyncio.to_thread(
            market_data_service.get_candles,
            symbol,
            period,
            interval,
        )
    except Exception as error:
        raise_http_error(error)
        raise


@router.get("/history-options")
def history_options() -> dict[str, list[str]]:
    """Indique à Avalonia les périodes et intervalles autorisés."""

    return {
        period: sorted(intervals)
        for period, intervals in ALLOWED_PERIOD_INTERVALS.items()
    }
