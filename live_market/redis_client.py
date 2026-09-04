"""Lecture et écriture des données du marché dans Redis."""

from redis.asyncio import Redis

from live_market.config import REDIS_URL
from live_market.market_schemas import LiveQuote


redis_client = Redis.from_url(REDIS_URL, decode_responses=True)


async def save_latest_quote(quote: LiveQuote) -> None:
    """Enregistre le dernier cours connu pendant 24 heures."""

    key = f"market:latest:{quote.symbol}"
    await redis_client.set(key, quote.model_dump_json(), ex=24 * 60 * 60)


async def get_latest_quote(symbol: str) -> LiveQuote | None:
    """Lit le dernier cours connu."""

    key = f"market:latest:{symbol}"
    data = await redis_client.get(key)

    if data is None:
        return None

    return LiveQuote.model_validate_json(data)
