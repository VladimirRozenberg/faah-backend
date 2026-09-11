"""Lecture et écriture du cache."""

from redis.asyncio import Redis

from live_market.config import CACHE_TTL_SECONDS, REDIS_URL
from live_market.market_schemas import LiveQuote


# decode_responses permet de lire du texte plutôt que des octets.
redis_client = Redis.from_url(REDIS_URL, decode_responses=True)


async def save_latest_quote(quote: LiveQuote) -> None:
    """Enregistre le dernier cours connu pendant 24 heures."""

    key = f"market:latest:{quote.symbol}"
    # Le nouveau JSON remplace le précédent et relance le délai de 24 heures.
    await redis_client.set(key, quote.model_dump_json(), ex=CACHE_TTL_SECONDS)


async def get_latest_quote(symbol: str) -> LiveQuote | None:
    """Lit le dernier cours connu."""

    key = f"market:latest:{symbol}"
    data = await redis_client.get(key)

    # Une clé absente ou expirée donne None. Une panne Redis lève une erreur.
    if data is None:
        return None

    # Reconstruire le cours à partir du JSON et vérifier ses types.
    return LiveQuote.model_validate_json(data)
