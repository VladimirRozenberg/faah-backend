"""Reçoit les cours Yahoo de tous les actifs et les transmet à Redis."""

import asyncio
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from time import monotonic

import yfinance as yf
from sqlalchemy import select

from assets.market_data import get_latest_daily_quotes
from db import AsyncSessionLocal
from live_market.market_schemas import LiveQuote, LiveWorkerStatus
from live_market.redis_client import (
    get_latest_quotes,
    get_recent_historical_fallback_attempts,
    mark_historical_fallback_attempted,
    save_historical_quote_if_stale,
    save_latest_quote,
    save_live_worker_status,
)
from models import Asset

logger = logging.getLogger(__name__)
WORKER_HEARTBEAT_INTERVAL_SECONDS = 15
ASSET_REFRESH_INTERVAL_SECONDS = 30
HISTORICAL_REFRESH_INTERVAL_SECONDS = 60
STALE_QUOTE_SECONDS = 60
INITIAL_RETRY_DELAY_SECONDS = 3
MAX_RETRY_DELAY_SECONDS = 60


@dataclass
class WorkerRuntime:
    subscribed_symbols: set[str] = field(default_factory=set)
    connected: bool = False
    running: bool = True
    quotes_received: int = 0
    last_quote_at: datetime | None = None
    live_prices: int = 0
    delayed_prices: int = 0
    unavailable_prices: int = 0
    error: str | None = None


async def publish_worker_status(runtime: WorkerRuntime) -> None:
    """Publish the current connection and subscription state to Redis."""

    try:
        await save_live_worker_status(
            LiveWorkerStatus(
                running=runtime.running,
                connected=runtime.connected,
                subscribed_assets=len(runtime.subscribed_symbols),
                last_heartbeat_at=datetime.now(timezone.utc),
                last_quote_at=runtime.last_quote_at,
                quotes_received=runtime.quotes_received,
                live_prices=runtime.live_prices,
                delayed_prices=runtime.delayed_prices,
                unavailable_prices=runtime.unavailable_prices,
                error=runtime.error,
            )
        )
    except Exception:
        logger.exception("Unable to publish live market worker heartbeat")


async def heartbeat_worker(runtime: WorkerRuntime) -> None:
    while True:
        await publish_worker_status(runtime)
        await asyncio.sleep(WORKER_HEARTBEAT_INTERVAL_SECONDS)


async def refresh_stale_historical_quotes(runtime: WorkerRuntime) -> None:
    """Fill Redis from daily Yahoo closes when no quote arrived in the last minute."""

    while True:
        try:
            symbols = await get_asset_symbols()
            cached_quotes = await get_latest_quotes(symbols)
            attempted_recently = await get_recent_historical_fallback_attempts(
                symbols
            )
            now = datetime.now(timezone.utc)
            stale_before = now - timedelta(seconds=STALE_QUOTE_SECONDS)
            stale_symbols = []
            for symbol in symbols:
                quote = cached_quotes.get(symbol)
                if quote is None:
                    stale_symbols.append(symbol)
                    continue

                quote_timestamp = quote.timestamp
                if quote_timestamp.tzinfo is None:
                    quote_timestamp = quote_timestamp.replace(
                        tzinfo=timezone.utc
                    )
                is_stale = quote_timestamp < stale_before
                is_missing_daily_fields = any(
                    value is None
                    for value in (
                        quote.day_volume,
                        quote.previous_close,
                        quote.change,
                        quote.change_percent,
                    )
                )
                if (
                    is_stale or is_missing_daily_fields
                ) and symbol not in attempted_recently:
                    stale_symbols.append(symbol)

            if stale_symbols:
                await mark_historical_fallback_attempted(stale_symbols)
                daily_quotes = await asyncio.to_thread(
                    get_latest_daily_quotes,
                    stale_symbols,
                )
                saved_count = 0
                for quote in daily_quotes:
                    if await save_historical_quote_if_stale(quote, stale_before):
                        saved_count += 1
                logger.info(
                    "Updated %d of %d stale market quotes from daily history",
                    saved_count,
                    len(stale_symbols),
                )

            quotes_for_counts = (
                await get_latest_quotes(symbols)
                if stale_symbols
                else cached_quotes
            )
            (
                runtime.live_prices,
                runtime.delayed_prices,
                runtime.unavailable_prices,
            ) = count_price_availability(
                symbols,
                quotes_for_counts,
                datetime.now(timezone.utc),
            )
        except Exception:
            logger.exception("Unable to refresh stale quotes from daily history")

        await asyncio.sleep(HISTORICAL_REFRESH_INTERVAL_SECONDS)


def count_price_availability(
    symbols: list[str],
    quotes: dict[str, LiveQuote],
    now: datetime,
) -> tuple[int, int, int]:
    """Count fresh live, cached-but-delayed, and missing asset prices."""

    live = 0
    delayed = 0
    unavailable = 0
    for symbol in symbols:
        quote = quotes.get(symbol)
        if quote is None:
            unavailable += 1
            continue

        timestamp = quote.timestamp
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        age_seconds = (now - timestamp).total_seconds()
        if (
            quote.source == "live"
            and 0 <= age_seconds <= STALE_QUOTE_SECONDS
        ):
            live += 1
        else:
            delayed += 1
    return live, delayed, unavailable


async def get_asset_symbols() -> list[str]:
    """Lit dans PostgreSQL tous les symboles d'actifs à suivre."""

    async with AsyncSessionLocal() as db:
        query = select(Asset.ast_symbol)
        symbols = await db.scalars(query)
        return sorted(
            {
                symbol.strip().upper()
                for symbol in symbols.all()
                if symbol and symbol.strip()
            }
        )


def create_quote(message: dict) -> LiveQuote | None:
    """Transforme un message yfinance en cours utilisable."""

    try:
        symbol = str(message["id"]).upper()
        price = float(message["price"])
        raw_time = int(message.get("time", 0))

        # Les dates Yahoo sont généralement en millisecondes depuis 1970.
        # datetime attend des secondes ; on accepte aussi ce format.
        if raw_time > 10_000_000_000:
            raw_time = raw_time / 1000

        if raw_time > 0:
            timestamp = datetime.fromtimestamp(raw_time, timezone.utc)
        else:
            timestamp = datetime.now(timezone.utc)

        raw_volume = message.get("day_volume")
        volume = None
        if raw_volume is not None:
            volume = int(raw_volume)

    except (KeyError, TypeError, ValueError):
        # Ignorer le message si une valeur obligatoire manque ou est invalide.
        return None

    if price <= 0:
        return None

    def optional_number(field: str) -> float | None:
        value = message.get(field)
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    return LiveQuote(
        symbol=symbol,
        price=price,
        timestamp=timestamp,
        day_volume=volume,
        previous_close=optional_number("previous_close"),
        change=optional_number("change"),
        change_percent=optional_number("change_percent"),
    )


async def process_message(message: dict, runtime: WorkerRuntime) -> None:
    """Enregistre dans Redis le dernier cours reçu."""

    quote = create_quote(message)

    if quote is None:
        return

    try:
        await save_latest_quote(quote)
    except Exception as error:
        runtime.error = f"Redis quote write failed ({type(error).__name__})"
        logger.exception("Unable to cache live quote for %s", quote.symbol)
        return

    runtime.quotes_received += 1
    runtime.last_quote_at = quote.timestamp
    runtime.error = None


async def add_new_symbols(websocket, runtime: WorkerRuntime) -> None:
    """Ajoute toutes les 30 secondes les nouveaux actifs détectés."""

    while True:
        await asyncio.sleep(ASSET_REFRESH_INTERVAL_SECONDS)

        try:
            database_symbols = set(await get_asset_symbols())
        except Exception as error:
            runtime.error = f"Asset lookup failed ({type(error).__name__})"
            logger.exception("Unable to refresh live market symbols")
            continue

        # La différence entre les deux ensembles donne les nouveaux symboles.
        # On ne se réabonne donc pas aux actifs déjà écoutés.
        new_symbols = database_symbols - runtime.subscribed_symbols

        if new_symbols:
            try:
                symbols_to_add = sorted(new_symbols)
                await websocket.subscribe(symbols_to_add)
                runtime.subscribed_symbols.update(new_symbols)
                runtime.error = None
                logger.info("Subscribed to %d new asset(s)", len(new_symbols))
                await publish_worker_status(runtime)
            except Exception as error:
                runtime.error = (
                    f"Asset subscription failed ({type(error).__name__})"
                )
                logger.exception(
                    "Unable to subscribe to %d new live market asset(s)",
                    len(new_symbols),
                )


async def stream_quotes(symbols: list[str], runtime: WorkerRuntime) -> None:
    """Gère une connexion Yahoo, de l'abonnement jusqu'à sa fermeture."""

    websocket = yf.AsyncWebSocket(verbose=False)
    update_task = None
    connected_at = None

    try:
        await websocket.subscribe(sorted(set(symbols)))
        runtime.subscribed_symbols.update(symbols)
        runtime.connected = True
        runtime.error = None
        connected_at = monotonic()
        await publish_worker_status(runtime)

        update_task = asyncio.create_task(add_new_symbols(websocket, runtime))

        logger.info("Connected to yfinance for %d asset(s)", len(symbols))

        async def handle_message(message: dict) -> None:
            await process_message(message, runtime)

        await websocket.listen(handle_message)

    except Exception as error:
        runtime.connected = False
        runtime.error = f"Live market websocket failed ({type(error).__name__})"
        await publish_worker_status(runtime)
        logger.exception("Live market websocket failed")

    finally:
        # Toujours arrêter la tâche liée à cette connexion avant de fermer.
        # cancel demande l'arrêt ; gather attend que la tâche soit terminée.
        if update_task is not None:
            update_task.cancel()
            await asyncio.gather(update_task, return_exceptions=True)

        try:
            await websocket.close()
        except Exception as error:
            runtime.error = f"Websocket close failed ({type(error).__name__})"
            logger.exception("Unable to close yfinance live websocket")
        runtime.connected = False
        runtime.subscribed_symbols.clear()
        if (
            connected_at is not None
            and monotonic() - connected_at >= MAX_RETRY_DELAY_SECONDS
        ):
            runtime.error = None
        await publish_worker_status(runtime)


async def listen_to_yfinance() -> None:
    """Relance l'écoute si elle se termine ou si aucun actif n'est disponible."""

    runtime = WorkerRuntime()
    heartbeat_task = asyncio.create_task(heartbeat_worker(runtime))
    historical_refresh_task = asyncio.create_task(
        refresh_stale_historical_quotes(runtime)
    )
    retry_delay = INITIAL_RETRY_DELAY_SECONDS
    try:
        while True:
            try:
                symbols = await get_asset_symbols()
                runtime.error = None
            except Exception as error:
                runtime.connected = False
                runtime.error = f"Asset lookup failed ({type(error).__name__})"
                logger.exception("Unable to load asset symbols for live worker")
                await asyncio.sleep(10)
                continue

            if not symbols:
                runtime.connected = False
                runtime.subscribed_symbols.clear()
                print("Aucun actif à suivre. Nouvelle vérification dans 10 secondes.")
                await asyncio.sleep(10)
                continue

            attempt_started = monotonic()
            await stream_quotes(symbols, runtime)

            if monotonic() - attempt_started >= MAX_RETRY_DELAY_SECONDS:
                retry_delay = INITIAL_RETRY_DELAY_SECONDS
            logger.info("Retrying live market connection in %d seconds", retry_delay)
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, MAX_RETRY_DELAY_SECONDS)
    finally:
        runtime.running = False
        runtime.connected = False
        runtime.subscribed_symbols.clear()
        heartbeat_task.cancel()
        historical_refresh_task.cancel()
        await asyncio.gather(
            heartbeat_task,
            historical_refresh_task,
            return_exceptions=True,
        )
        await publish_worker_status(runtime)


if __name__ == "__main__":
    asyncio.run(listen_to_yfinance())
