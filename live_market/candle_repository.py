"""Enregistrement et lecture des bougies dans PostgreSQL."""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from db import AsyncSessionLocal
from live_market.market_schemas import LiveCandle
from models import Asset, MarketData


def to_database_time(timestamp: datetime) -> datetime:
    """Convertit l'heure UTC pour la colonne TIMESTAMP de PostgreSQL."""

    if timestamp.tzinfo is None:
        return timestamp

    return timestamp.astimezone(timezone.utc).replace(tzinfo=None)


async def save_candles(candles: list[LiveCandle]) -> int:
    """Crée les bougies ou les met à jour si elles existent déjà."""

    if not candles:
        return 0

    symbols = {candle.symbol for candle in candles}

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Asset.ast_symbol, Asset.ast_id).where(
                Asset.ast_symbol.in_(symbols)
            )
        )
        asset_ids = dict(result.all())

        rows = []

        for candle in candles:
            asset_id = asset_ids.get(candle.symbol)

            # Une bougie ne peut pas être enregistrée sans son Asset.
            if asset_id is None:
                continue

            rows.append(
                {
                    "mkt_ast_id": asset_id,
                    "mkt_timeframe": candle.timeframe,
                    "mkt_open": Decimal(str(candle.open)),
                    "mkt_high": Decimal(str(candle.high)),
                    "mkt_low": Decimal(str(candle.low)),
                    "mkt_close": Decimal(str(candle.close)),
                    "mkt_volume": candle.volume,
                    "mkt_timestamp": to_database_time(candle.timestamp),
                    "mkt_source": "Yahoo Finance via yfinance",
                }
            )

        if not rows:
            return 0

        query = insert(MarketData).values(rows)

        # Si la bougie existe déjà, ses valeurs sont actualisées.
        query = query.on_conflict_do_update(
            index_elements=[
                "mkt_ast_id",
                "mkt_timeframe",
                "mkt_timestamp",
            ],
            set_={
                "mkt_open": query.excluded.mkt_open,
                "mkt_high": query.excluded.mkt_high,
                "mkt_low": query.excluded.mkt_low,
                "mkt_close": query.excluded.mkt_close,
                "mkt_volume": query.excluded.mkt_volume,
                "mkt_source": query.excluded.mkt_source,
            },
        )

        await session.execute(query)
        await session.commit()

    return len(rows)


async def save_candle(candle: LiveCandle) -> None:
    """Enregistre une seule bougie."""

    await save_candles([candle])


async def read_candles(
    symbol: str,
    timeframe: str,
    limit: int,
) -> list[LiveCandle]:
    """Lit les dernières bougies dans l'ordre chronologique."""

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(MarketData)
            .join(Asset, Asset.ast_id == MarketData.mkt_ast_id)
            .where(
                Asset.ast_symbol == symbol,
                MarketData.mkt_timeframe == timeframe,
            )
            .order_by(MarketData.mkt_timestamp.desc())
            .limit(limit)
        )
        database_candles = list(result.scalars().all())

    database_candles.reverse()

    candles = []

    for row in database_candles:
        timestamp = row.mkt_timestamp

        # Les heures de la base sont enregistrées en UTC sans fuseau écrit.
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        candles.append(
            LiveCandle(
                symbol=symbol,
                timeframe=row.mkt_timeframe,
                timestamp=timestamp,
                open=float(row.mkt_open),
                high=float(row.mkt_high),
                low=float(row.mkt_low),
                close=float(row.mkt_close),
                volume=int(row.mkt_volume or 0),
            )
        )

    return candles
