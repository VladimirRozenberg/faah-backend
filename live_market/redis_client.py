"""Lecture et écriture des données du marché dans Redis."""

from redis.asyncio import Redis

from live_market.config import REDIS_URL, TIMEFRAME
from live_market.market_schemas import CandleState, LiveQuote


redis_client = Redis.from_url(REDIS_URL, decode_responses=True)


async def save_latest_quote(quote: LiveQuote) -> None:
    """Enregistre le dernier cours connu pendant 24 heures."""

    key = f"market:latest:{quote.symbol}"
    await redis_client.set(
        key,
        quote.model_dump_json(),
        ex=86400,
    )


async def get_latest_quote(symbol: str) -> LiveQuote | None:
    """Lit le dernier cours connu."""

    key = f"market:latest:{symbol}"
    data = await redis_client.get(key)

    if data is None:
        return None

    return LiveQuote.model_validate_json(data)


async def save_current_candle(candle: CandleState) -> None:
    """Enregistre la bougie encore en construction pendant 48 heures."""

    key = f"market:candle:{candle.symbol}:{TIMEFRAME}"
    await redis_client.set(
        key,
        candle.model_dump_json(),
        ex=172800,
    )


async def get_current_candle(symbol: str) -> CandleState | None:
    """Lit la bougie encore en construction."""

    key = f"market:candle:{symbol}:{TIMEFRAME}"
    data = await redis_client.get(key)

    if data is None:
        return None

    return CandleState.model_validate_json(data)


async def close_redis() -> None:
    """Ferme proprement la connexion Redis."""

    await redis_client.aclose()
