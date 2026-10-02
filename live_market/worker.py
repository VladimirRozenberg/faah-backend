"""Reçoit les cours Yahoo de tous les actifs et les transmet à Redis."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import yfinance as yf
from sqlalchemy import select

from db import AsyncSessionLocal
from live_market.market_schemas import LiveQuote, LiveWorkerStatus
from live_market.redis_client import save_latest_quote, save_live_worker_status
from models import Asset

logger = logging.getLogger(__name__)
WORKER_HEARTBEAT_INTERVAL_SECONDS = 15


@dataclass
class WorkerRuntime:
    subscribed_symbols: set[str] = field(default_factory=set)
    connected: bool = False
    running: bool = True
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
                error=runtime.error,
            )
        )
    except Exception:
        logger.exception("Unable to publish live market worker heartbeat")


async def heartbeat_worker(runtime: WorkerRuntime) -> None:
    while True:
        await publish_worker_status(runtime)
        await asyncio.sleep(WORKER_HEARTBEAT_INTERVAL_SECONDS)


async def get_asset_symbols() -> list[str]:
    """Lit dans PostgreSQL tous les symboles d'actifs à suivre."""

    async with AsyncSessionLocal() as db:
        query = select(Asset.ast_symbol)
        symbols = await db.scalars(query)
        return list(symbols.all())


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

    return LiveQuote(
        symbol=symbol,
        price=price,
        timestamp=timestamp,
        day_volume=volume,
    )


async def process_message(message: dict) -> None:
    """Enregistre dans Redis le dernier cours reçu."""

    quote = create_quote(message)

    if quote is not None:
        await save_latest_quote(quote)


async def add_new_symbols(websocket, runtime: WorkerRuntime) -> None:
    """Ajoute toutes les 30 secondes les nouveaux actifs détectés."""

    while True:
        await asyncio.sleep(30)

        try:
            database_symbols = set(await get_asset_symbols())
            runtime.error = None
        except Exception as error:
            runtime.error = f"Asset lookup failed: {error}"
            print(f"Impossible de relire les actifs : {error}")
            continue

        # La différence entre les deux ensembles donne les nouveaux symboles.
        # On ne se réabonne donc pas aux actifs déjà écoutés.
        new_symbols = database_symbols - runtime.subscribed_symbols

        if new_symbols:
            await websocket.subscribe(list(new_symbols))
            runtime.subscribed_symbols.update(new_symbols)
            print(f"Nouveaux symboles suivis : {sorted(new_symbols)}")
            await publish_worker_status(runtime)


async def stream_quotes(symbols: list[str], runtime: WorkerRuntime) -> None:
    """Gère une connexion Yahoo, de l'abonnement jusqu'à sa fermeture."""

    websocket = yf.AsyncWebSocket(verbose=False)
    update_task = None

    try:
        await websocket.subscribe(symbols)
        runtime.subscribed_symbols.update(symbols)
        runtime.connected = True
        runtime.error = None
        await publish_worker_status(runtime)

        # [IA-04] Partie technique avec l'aide de l'IA : cette tâche
        # vérifie les nouveaux actifs pendant que listen reçoit les cours.
        # await laisse les autres tâches avancer pendant une attente.
        update_task = asyncio.create_task(add_new_symbols(websocket, runtime))

        print(f"Connexion yfinance ouverte pour {len(symbols)} actif(s).")
        await websocket.listen(process_message)

    except Exception as error:
        runtime.connected = False
        runtime.error = str(error)
        await publish_worker_status(runtime)
        print(f"Erreur yfinance : {error}")

    finally:
        # Toujours arrêter la tâche liée à cette connexion avant de fermer.
        # cancel demande l'arrêt ; gather attend que la tâche soit terminée.
        if update_task is not None:
            update_task.cancel()
            await asyncio.gather(update_task, return_exceptions=True)

        try:
            await websocket.close()
        except Exception as error:
            runtime.error = str(error)
            logger.exception("Unable to close yfinance live websocket")
        runtime.connected = False
        runtime.subscribed_symbols.clear()
        await publish_worker_status(runtime)


async def listen_to_yfinance() -> None:
    """Relance l'écoute si elle se termine ou si aucun actif n'est disponible."""

    runtime = WorkerRuntime()
    heartbeat_task = asyncio.create_task(heartbeat_worker(runtime))
    try:
        while True:
            try:
                symbols = await get_asset_symbols()
                runtime.error = None
            except Exception as error:
                runtime.connected = False
                runtime.error = f"Asset lookup failed: {error}"
                logger.exception("Unable to load asset symbols for live worker")
                await asyncio.sleep(10)
                continue

            if not symbols:
                runtime.connected = False
                runtime.subscribed_symbols.clear()
                print("Aucun actif à suivre. Nouvelle vérification dans 10 secondes.")
                await asyncio.sleep(10)
                continue

            await stream_quotes(symbols, runtime)

            print("Nouvelle tentative dans 3 secondes...")
            await asyncio.sleep(3)
    finally:
        runtime.running = False
        runtime.connected = False
        runtime.subscribed_symbols.clear()
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)
        await publish_worker_status(runtime)


if __name__ == "__main__":
    asyncio.run(listen_to_yfinance())
