"""Reçoit les cours Yahoo des actifs suivis et les transmet à Redis."""

import asyncio
from datetime import datetime, timezone

import yfinance as yf
from sqlalchemy import select

from db import AsyncSessionLocal
from live_market.redis_client import save_latest_quote
from live_market.market_schemas import LiveQuote
from models import Asset


async def get_tracked_symbols() -> list[str]:
    """Lit dans PostgreSQL les symboles que le worker doit suivre."""

    async with AsyncSessionLocal() as db:
        query = select(Asset.ast_symbol).where(Asset.ast_is_tracked.is_(True))
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


async def add_new_symbols(websocket, subscribed: set[str]) -> None:
    """Ajoute toutes les 30 secondes les nouveaux actifs détectés."""

    while True:
        await asyncio.sleep(30)

        try:
            database_symbols = set(await get_tracked_symbols())
        except Exception as error:
            print(f"Impossible de relire les actifs : {error}")
            continue

        # La différence entre les deux ensembles donne les nouveaux symboles.
        # On ne se réabonne donc pas aux actifs déjà écoutés.
        new_symbols = database_symbols - subscribed

        if new_symbols:
            await websocket.subscribe(list(new_symbols))
            subscribed.update(new_symbols)
            print(f"Nouveaux symboles suivis : {sorted(new_symbols)}")


async def stream_quotes(symbols: list[str]) -> None:
    """Gère une connexion Yahoo, de l'abonnement jusqu'à sa fermeture."""

    websocket = yf.AsyncWebSocket(verbose=False)
    update_task = None

    try:
        await websocket.subscribe(symbols)

        # [IA-04] Partie technique avec l'aide de l'IA : cette tâche
        # vérifie les nouveaux actifs pendant que listen reçoit les cours.
        # await laisse les autres tâches avancer pendant une attente.
        update_task = asyncio.create_task(add_new_symbols(websocket, set(symbols)))

        print(f"Connexion yfinance ouverte pour {len(symbols)} actif(s).")
        await websocket.listen(process_message)

    except Exception as error:
        print(f"Erreur yfinance : {error}")

    finally:
        # Toujours arrêter la tâche liée à cette connexion avant de fermer.
        # cancel demande l'arrêt ; gather attend que la tâche soit terminée.
        if update_task is not None:
            update_task.cancel()
            await asyncio.gather(update_task, return_exceptions=True)

        await websocket.close()


async def listen_to_yfinance() -> None:
    """Relance l'écoute si elle se termine ou si aucun actif n'est disponible."""

    while True:
        try:
            symbols = await get_tracked_symbols()
        except Exception:
            await asyncio.sleep(10)
            continue

        if not symbols:
            print("Aucun actif à suivre. Nouvelle vérification dans 10 secondes.")
            await asyncio.sleep(10)
            continue

        await stream_quotes(symbols)

        print("Nouvelle tentative dans 3 secondes...")
        await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(listen_to_yfinance())
