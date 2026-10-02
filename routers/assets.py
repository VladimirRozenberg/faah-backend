"""Routes HTTP liées aux actifs et à leur historique."""

import asyncio
import logging
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from assets.market_data import (
    ALLOWED_PERIOD_INTERVALS,
    InvalidHistoryRequestError,
    MarketDataUnavailableError,
    get_candles,
    get_market_asset,
    get_market_assets,
)

from assets.schemas import (
    AssetItem,
    AssetListItem,
    AssetListResponse,
    AssetSummary,
    CandleResponse,
    MarketListResponse,
    NicheItem,
    NicheListResponse,
)

from auth.login import CurrentUser
from db import DbSession
from live_market.market_schemas import LiveQuote
from live_market.redis_client import get_latest_quote
from models import (
    Asset,
    AssetNiche,
    ClassificationAsset,
    Crypto,
    DataSource,
    Favorite,
    Forex,
    Future,
    Niche,
    SourceClassification,
    Stock,
)



# Toutes les routes de ce fichier commencent par /api et sont regroupées
# sous le titre « Marché » dans la documentation Swagger.
router = APIRouter(prefix="/api", tags=["Marché"])
logger = logging.getLogger(__name__)


async def find_asset_or_404(db: DbSession, symbol: str) -> Asset:
    """Recherche commune aux routes qui demandent un actif précis."""

    symbol = symbol.upper()
    asset = await db.scalar(select(Asset).where(Asset.ast_symbol == symbol))

    if asset is None:
        raise HTTPException(status_code=404, detail=f"L'actif {symbol} n'existe pas.")

    return asset


async def create_asset_item(
    db: AsyncSession,
    asset: Asset,
) -> AssetItem:
    """Transforme un Asset PostgreSQL en réponse complète."""

    item = AssetItem(
        logo_url=(f"/api/assets/{quote(asset.ast_symbol, safe='')}/logo"
                  if asset.ast_logo_mime_type else None),
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

    # Ajouter seulement les informations qui correspondent au type de l'actif.
    # Les autres champs facultatifs restent à None (null dans le JSON).
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
            if future.fut_contract_size is not None:
                item.contract_size = float(future.fut_contract_size)

    return item


async def add_market_information(
    assets: list[Asset],
    items: list[AssetListItem],
) -> None:
    """Attach cached live quotes and fetch uncached assets from Yahoo in one batch."""

    if not assets:
        return

    async def read_quote(symbol: str) -> LiveQuote | None:
        try:
            return await get_latest_quote(symbol)
        except Exception:
            logger.exception("Cached market quote unavailable for %s", symbol)
            return None

    quotes = await asyncio.gather(
        *(read_quote(asset.ast_symbol) for asset in assets)
    )
    quotes_by_symbol = {
        quote.symbol: quote for quote in quotes if quote is not None
    }
    assets_by_symbol = {asset.ast_symbol: asset for asset in assets}
    missing_assets = [
        asset for asset in assets if asset.ast_symbol not in quotes_by_symbol
    ]
    fallback_by_symbol = {}
    if missing_assets:
        try:
            summaries = await asyncio.to_thread(get_market_assets, missing_assets)
            fallback_by_symbol = {
                summary.symbol: summary for summary in summaries
            }
        except Exception:
            logger.exception(
                "Market information unavailable for %d uncached asset(s)",
                len(missing_assets),
            )

    for item in items:
        cached_quote = quotes_by_symbol.get(item.symbol)
        if cached_quote is None:
            item.market = fallback_by_symbol.get(item.symbol)
            continue

        asset = assets_by_symbol[item.symbol]
        item.market = AssetSummary(
            symbol=cached_quote.symbol,
            name=asset.ast_name,
            type=asset.ast_type,
            logo_url=(
                f"/api/assets/{quote(asset.ast_symbol, safe='')}/logo"
                if asset.ast_logo_mime_type
                else None
            ),
            exchange=asset.ast_exchange,
            currency=asset.ast_currency or "USD",
            last_price=cached_quote.price,
            previous_close=None,
            change=None,
            change_percent=None,
            volume=cached_quote.day_volume,
            retrieved_at=cached_quote.timestamp,
            source="Redis live quote",
        )


def create_http_error(error: Exception) -> HTTPException:
    """Convertit les erreurs du service en réponses HTTP compréhensibles."""

    if isinstance(error, InvalidHistoryRequestError):
        return HTTPException(status_code=400, detail=str(error))
    if isinstance(error, MarketDataUnavailableError):
        return HTTPException(status_code=502, detail=str(error))
    # Une erreur inattendue reste une erreur serveur, sans être masquée.
    raise error


@router.get("/assets", response_model=AssetListResponse)
async def list_assets(
    db: DbSession,
    user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str = Query(default="", max_length=200),
    favorites_only: bool = False,
    # Query indique que ces listes viennent de l'URL, et non d'un corps JSON.
    asset_type: Annotated[list[Literal["stock", "crypto", "forex", "future"]] | None, Query()] = None,
    niche_id: Annotated[list[int] | None, Query()] = None,
    exchange: Annotated[list[str] | None, Query()] = None,
    country: Annotated[list[str] | None, Query()] = None,
    currency: Annotated[list[str] | None, Query()] = None,
    sector: Annotated[list[str] | None, Query()] = None,
    industry: Annotated[list[str] | None, Query()] = None,
    base_currency: Annotated[list[str] | None, Query()] = None,
    quote_currency: Annotated[list[str] | None, Query()] = None,
) -> AssetListResponse:
    """Filter the catalog before pagination and attach market data to this page."""

    filters = []
    term = search.strip()
    if term:
        # ILIKE ignore la casse. Échapper % et _ pour les chercher littéralement.
        pattern = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        filters.append(or_(Asset.ast_symbol.ilike(pattern, escape="\\"), Asset.ast_name.ilike(pattern, escape="\\")))

    favorite_asset_ids = select(Favorite.fav_ast_id).where(
        Favorite.fav_usr_id == user.user_id
    )
    if favorites_only:
        filters.append(Asset.ast_id.in_(favorite_asset_ids))

    if asset_type:
        filters.append(Asset.ast_type.in_(asset_type))
    if niche_id:
        filters.append(
            Asset.ast_id.in_(
                select(AssetNiche.ani_ast_id).where(
                    AssetNiche.ani_nic_id.in_(set(niche_id))
                )
            )
        )

    for values, column in (
        (exchange, Asset.ast_exchange),
        (country, Asset.ast_country),
        (currency, Asset.ast_currency),
    ):
        selected = [value.strip() for value in values or [] if value.strip()]
        if selected:
            # Recherche partielle, insensible à la casse, avant la pagination.
            # Échapper les caractères spéciaux pour que la saisie reste littérale.
            patterns = [
                "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                for value in selected
            ]
            filters.append(or_(*(column.ilike(pattern, escape="\\") for pattern in patterns)))

    stock_sectors = [value.strip() for value in sector or [] if value.strip()]
    if stock_sectors:
        filters.append(
            Asset.ast_id.in_(
                select(Stock.sto_ast_id).where(Stock.sto_sector.in_(set(stock_sectors)))
            )
        )

    stock_industries = [value.strip() for value in industry or [] if value.strip()]
    if stock_industries:
        filters.append(
            Asset.ast_id.in_(
                select(Stock.sto_ast_id).where(
                    Stock.sto_industry.in_(set(stock_industries))
                )
            )
        )

    forex_base_currencies = [
        value.strip() for value in base_currency or [] if value.strip()
    ]
    if forex_base_currencies:
        filters.append(
            Asset.ast_id.in_(
                select(Forex.for_ast_id).where(
                    Forex.for_base_currency.in_(set(forex_base_currencies))
                )
            )
        )

    forex_quote_currencies = [
        value.strip() for value in quote_currency or [] if value.strip()
    ]
    if forex_quote_currencies:
        filters.append(
            Asset.ast_id.in_(
                select(Forex.for_ast_id).where(
                    Forex.for_quote_currency.in_(set(forex_quote_currencies))
                )
            )
        )

    total = await db.scalar(
        select(func.count()).select_from(Asset).where(*filters)
    ) or 0

    favorite_order = case(
        (Asset.ast_id.in_(favorite_asset_ids), 0),
        else_=1,
    )

    result = await db.execute(
        select(Asset)
        .where(*filters)
        .order_by(
            favorite_order,
            Asset.ast_type,
            Asset.ast_name,
            Asset.ast_id,
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    database_assets = list(result.scalars().all())

    items = []
    for asset in database_assets:
        item = await create_asset_item(db, asset)
        items.append(AssetListItem.model_validate(item.model_dump()))
    await add_market_information(database_assets, items)

    return AssetListResponse(
        count=total,
        page=page,
        page_size=page_size,
        items=items,
    )


@router.get("/niches", response_model=NicheListResponse)
async def list_niches(db: DbSession) -> NicheListResponse:
    """Return the curated niche catalog used by portfolio preferences."""

    niches = list(
        (
            await db.scalars(
                select(Niche).order_by(
                    Niche.nic_category,
                    Niche.nic_name,
                    Niche.nic_id,
                )
            )
        ).all()
    )
    return NicheListResponse(
        count=len(niches),
        items=[
            NicheItem(
                id=niche.nic_id,
                name=niche.nic_name,
                category=niche.nic_category,
                description=niche.nic_description,
            )
            for niche in niches
        ],
    )


@router.get("/market", response_model=MarketListResponse)
async def list_market(
    db: DbSession,
    user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> MarketListResponse:
    """Retourne les prix des 20 actifs de la page demandée."""

    try:
        total = await db.scalar(
            select(func.count())
            .select_from(Asset)
            .where(Asset.ast_is_tracked.is_(True))
        ) or 0

        favorite_asset_ids = select(Favorite.fav_ast_id).where(
            Favorite.fav_usr_id == user.user_id
        )

        favorite_order = case(
            (Asset.ast_id.in_(favorite_asset_ids), 0),
            else_=1,
        )

        result = await db.execute(
            select(Asset)
            .where(Asset.ast_is_tracked.is_(True))
            .order_by(
                favorite_order,
                Asset.ast_type,
                Asset.ast_name,
                Asset.ast_id,
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        database_assets = list(result.scalars().all())

        items = await asyncio.to_thread(
            get_market_assets,
            database_assets,
        )

        return MarketListResponse(
            count=total,
            page=page,
            page_size=page_size,
            items=items,
        )

    except Exception as error:
        raise create_http_error(error) from error


@router.get("/assets/{symbol}", response_model=AssetItem)
async def get_asset(symbol: str, db: DbSession) -> AssetItem:
    """Recherche un actif dans PostgreSQL avec son symbole."""

    asset = await find_asset_or_404(db, symbol)
    return await create_asset_item(db, asset)


@router.get("/assets/{symbol}/market", response_model=AssetSummary)
async def get_asset_market(symbol: str, db: DbSession) -> AssetSummary:
    """Retourne le prix et la variation d'un actif avec yfinance."""

    asset = await find_asset_or_404(db, symbol)

    try:
        return await asyncio.to_thread(get_market_asset, asset)
    except Exception as error:
        raise create_http_error(error) from error


@router.get("/assets/{symbol}/candles", response_model=CandleResponse)
async def get_asset_candles(
    symbol: str,
    db: DbSession,
    period: str = Query(default="1d", description="Exemples : 1d, 5d, 1mo, 1y"),
    interval: str = Query(default="5m", description="Exemples : 1m, 5m, 1h, 1d"),
) -> CandleResponse:
    """Retourne les bougies OHLCV qui serviront au graphique Avalonia."""

    symbol = symbol.upper()
    await find_asset_or_404(db, symbol)

    try:
        return await asyncio.to_thread(
            get_candles,
            symbol,
            period,
            interval,
        )
    except Exception as error:
        raise create_http_error(error) from error


@router.get("/history-options")
def history_options() -> dict[str, list[str]]:
    """Indique à Avalonia les périodes et intervalles autorisés."""

    return {
        period: sorted(intervals)
        for period, intervals in ALLOWED_PERIOD_INTERVALS.items()
    }


@router.get("/assets/{symbol}/news")
async def get_asset_news(symbol: str, db: DbSession) -> dict:
    """Actualités liées à l'actif par une classification enregistrée en base."""
    asset = await find_asset_or_404(db, symbol)

    # Suivre les liens en base, sans rechercher le nom de l'actif dans le texte.
    # DISTINCT évite les doublons si une actualité a plusieurs classifications.
    result = await db.execute(
        select(*DataSource.__table__.c)
        .join(SourceClassification, SourceClassification.cls_src_id == DataSource.src_id)
        .join(ClassificationAsset, ClassificationAsset.cla_cls_id == SourceClassification.cls_id)
        .where(ClassificationAsset.cla_ast_id == asset.ast_id)
        .distinct()
        .order_by(DataSource.src_created_at.desc(), DataSource.src_id.desc())
    )
    items = [dict(row) for row in result.mappings().all()]
    return {"count": len(items), "items": items}


@router.get("/assets/{symbol}/logo", response_class=Response)
async def get_asset_logo(symbol: str, db: DbSession) -> Response:
    """Retourne l'image stockée en base ; 404 permet de garder les initiales."""
    result = await db.execute(
        select(Asset.ast_logo, Asset.ast_logo_mime_type)
        .where(Asset.ast_symbol == symbol.upper())
    )
    row = result.first()
    if row is None or not row[0] or not row[1]:
        raise HTTPException(status_code=404, detail="Logo indisponible.")
    return Response(
        content=row[0], media_type=row[1],
        headers={"X-Content-Type-Options": "nosniff"},
    )
