"""Reçoit les cours yfinance des actifs suivis dans PostgreSQL."""

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
        result = await db.execute(
            select(Asset.ast_symbol).where(
                Asset.ast_is_tracked.is_(True)
            )
        )
        return list(result.scalars().all())


def create_quote(message: dict) -> LiveQuote | None:
    """Transforme un message yfinance en cours utilisable."""

    try:
        symbol = str(message["id"]).upper()
        price = float(message["price"])
        raw_time = int(message.get("time", 0))

        # Yahoo envoie normalement le temps en millisecondes.
        if raw_time > 10_000_000_000:
            raw_time = raw_time / 1000

        if raw_time > 0:
            timestamp = datetime.fromtimestamp(raw_time, timezone.utc)
        else:
            timestamp = datetime.now(timezone.utc)

        raw_volume = message.get("day_volume")
        volume = int(raw_volume) if raw_volume is not None else None

    except (KeyError, TypeError, ValueError):
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

        new_symbols = database_symbols - subscribed

        if new_symbols:
            await websocket.subscribe(list(new_symbols))
            subscribed.update(new_symbols)
            print(f"Nouveaux symboles suivis : {sorted(new_symbols)}")


async def listen_to_yfinance() -> None:
    """Écoute Yahoo et se reconnecte si la connexion est coupée."""

    while True:
        symbols = await get_tracked_symbols()

        if not symbols:
            print("Aucun actif à suivre. Nouvelle vérification dans 10 secondes.")
            await asyncio.sleep(10)
            continue

        websocket = yf.AsyncWebSocket(verbose=False)
        update_task = None

        try:
            await websocket.subscribe(symbols)
            subscribed = set(symbols)
            update_task = asyncio.create_task(
                add_new_symbols(websocket, subscribed)
            )

            print(f"Connexion yfinance ouverte pour {len(symbols)} actif(s).")
            await websocket.listen(process_message)

        except Exception as error:
            print(f"Erreur yfinance : {error}")

        finally:
            if update_task is not None:
                update_task.cancel()
                await asyncio.gather(update_task, return_exceptions=True)

            await websocket.close()

        print("Nouvelle tentative dans 3 secondes...")
        await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(listen_to_yfinance())
