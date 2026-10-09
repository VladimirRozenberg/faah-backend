"""Lecture et écriture du cache."""

import logging
from datetime import datetime

from redis.asyncio import Redis

from live_market.config import CACHE_TTL_SECONDS, REDIS_URL
from live_market.market_schemas import LiveQuote, LiveWorkerStatus


# decode_responses permet de lire du texte plutôt que des octets.
redis_client = Redis.from_url(REDIS_URL, decode_responses=True)
logger = logging.getLogger(__name__)
LIVE_WORKER_STATUS_KEY = "market:worker:status"
LIVE_WORKER_STATUS_TTL_SECONDS = 60
HISTORICAL_FALLBACK_TTL_SECONDS = 15 * 60
HISTORICAL_FALLBACK_KEY_PREFIX = "market:fallback-attempt:v2:"
# [IA-10] Partie technique avec l'aide de l'IA : ces scripts Lua s’exécutent directement dans Redis, sans interruption.
# Ils lisent le cours présent, gardent le prix le plus pertinent et fusionnent les champs.
# Cela évite qu’une écriture concurrente arrive entre la lecture et la sauvegarde.
# Les timestamps sont comparés comme du texte : un format de date cohérent est nécessaire.
MERGE_QUOTE_FIELDS_SCRIPT = """
local incoming = cjson.decode(ARGV[1])
local current_json = redis.call('GET', KEYS[1])
if current_json then
    local ok, current = pcall(cjson.decode, current_json)
    if ok and current['timestamp'] then
        if current['timestamp'] > incoming['timestamp'] then
            incoming['price'] = current['price']
            incoming['timestamp'] = current['timestamp']
            incoming['source'] = current['source'] or 'live'
        end
        for _, field in ipairs({'day_volume', 'previous_close', 'change', 'change_percent'}) do
            if incoming[field] == nil or incoming[field] == cjson.null then
                if current[field] ~= nil and current[field] ~= cjson.null then
                    incoming[field] = current[field]
                end
            end
        end
    end
end
redis.call('SET', KEYS[1], cjson.encode(incoming), 'EX', ARGV[2])
return 1
"""
SAVE_HISTORICAL_IF_STALE_SCRIPT = """
local incoming = cjson.decode(ARGV[1])
local current_json = redis.call('GET', KEYS[1])
if current_json then
    local ok, current = pcall(cjson.decode, current_json)
    if ok and current['timestamp'] then
        if current['source'] == 'live' and current['timestamp'] >= ARGV[2] then
            incoming['price'] = current['price']
            incoming['timestamp'] = current['timestamp']
            incoming['source'] = 'live'
            for _, field in ipairs({'day_volume', 'previous_close', 'change', 'change_percent'}) do
                if current[field] ~= nil and current[field] ~= cjson.null then
                    incoming[field] = current[field]
                end
            end
        elseif current['timestamp'] > incoming['timestamp'] then
            incoming['price'] = current['price']
            incoming['timestamp'] = current['timestamp']
            incoming['source'] = current['source'] or 'live'
            for _, field in ipairs({'day_volume', 'previous_close', 'change', 'change_percent'}) do
                if incoming[field] == nil or incoming[field] == cjson.null then
                    if current[field] ~= nil and current[field] ~= cjson.null then
                        incoming[field] = current[field]
                    end
                end
            end
        end
    end
end
redis.call('SET', KEYS[1], cjson.encode(incoming), 'EX', ARGV[3])
return 1
"""


async def save_latest_quote(quote: LiveQuote) -> None:
    """Store the latest quote while retaining fields absent from a live tick."""

    key = f"market:latest:{quote.symbol}"
    await redis_client.eval(
        MERGE_QUOTE_FIELDS_SCRIPT,
        1,
        key,
        quote.model_dump_json(),
        CACHE_TTL_SECONDS,
    )


async def get_latest_quote(symbol: str) -> LiveQuote | None:
    """Lit le dernier cours connu."""

    key = f"market:latest:{symbol}"
    data = await redis_client.get(key)

    # Une clé absente ou expirée donne None. Une panne Redis lève une erreur.
    if data is None:
        return None

    # Reconstruire le cours à partir du JSON et vérifier ses types.
    return LiveQuote.model_validate_json(data)


async def get_latest_quotes(symbols: list[str]) -> dict[str, LiveQuote]:
    """Read a set of current quotes in a single Redis request."""

    if not symbols:
        return {}
    values = await redis_client.mget(
        [f"market:latest:{symbol}" for symbol in symbols]
    )
    quotes = {}
    for symbol, value in zip(symbols, values):
        if value is None:
            continue
        try:
            quotes[symbol] = LiveQuote.model_validate_json(value)
        except Exception:
            logger.exception(
                "Invalid cached market quote for %s",
                symbol,
            )
    return quotes


async def get_recent_historical_fallback_attempts(
    symbols: list[str],
) -> set[str]:
    """Return symbols whose historical fallback was fetched recently."""

    if not symbols:
        return set()
    values = await redis_client.mget(
        [f"{HISTORICAL_FALLBACK_KEY_PREFIX}{symbol}" for symbol in symbols]
    )
    return {
        symbol for symbol, value in zip(symbols, values) if value is not None
    }


async def mark_historical_fallback_attempted(symbols: list[str]) -> None:
    """Rate-limit historical lookups, including symbols Yahoo cannot price."""

    if not symbols:
        return
    async with redis_client.pipeline(transaction=False) as pipeline:
        for symbol in symbols:
            pipeline.set(
                f"{HISTORICAL_FALLBACK_KEY_PREFIX}{symbol}",
                "1",
                ex=HISTORICAL_FALLBACK_TTL_SECONDS,
            )
        await pipeline.execute()


async def save_historical_quote_if_stale(
    quote: LiveQuote,
    stale_before: datetime,
) -> bool:
    """Store a daily quote only if no fresh or newer quote is already cached."""

    result = await redis_client.eval(
        SAVE_HISTORICAL_IF_STALE_SCRIPT,
        1,
        f"market:latest:{quote.symbol}",
        quote.model_dump_json(),
        stale_before.isoformat(),
        CACHE_TTL_SECONDS,
    )
    return bool(result)


async def save_live_worker_status(status: LiveWorkerStatus) -> None:
    """Publish a worker heartbeat that expires if the worker stops reporting."""

    await redis_client.set(
        LIVE_WORKER_STATUS_KEY,
        status.model_dump_json(),
        ex=LIVE_WORKER_STATUS_TTL_SECONDS,
    )


async def get_live_worker_status() -> LiveWorkerStatus | None:
    """Read the worker heartbeat, or None when no live heartbeat exists."""

    data = await redis_client.get(LIVE_WORKER_STATUS_KEY)
    if data is None:
        return None
    return LiveWorkerStatus.model_validate_json(data)


async def save_opportunity_sample(quote: LiveQuote) -> None:
    """Keep the last minute-level sample used by the opportunity detector."""

    key = f"market:opportunity-sample:{quote.symbol}"
    await redis_client.set(key, quote.model_dump_json(), ex=CACHE_TTL_SECONDS)


async def get_opportunity_sample(symbol: str) -> LiveQuote | None:
    """Return the preceding opportunity-detector sample for one asset."""

    key = f"market:opportunity-sample:{symbol}"
    data = await redis_client.get(key)
    if data is None:
        return None
    return LiveQuote.model_validate_json(data)
