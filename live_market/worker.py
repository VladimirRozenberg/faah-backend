"""Reçoit les cours yfinance et met les bougies à jour."""

import asyncio
from datetime import datetime, timezone

import yfinance as yf

from live_market.candle_builder import update_candle
from live_market.candle_repository import save_candle
from live_market.history_loader import backfill_recent_history
from live_market.redis_client import (
    get_current_candle,
    save_current_candle,
    save_latest_quote,
)
from live_market.market_schemas import LiveQuote
from market_data import TECH_STOCKS


def create_quote(message: dict) -> LiveQuote | None:
    """Transforme un message yfinance en cours utilisable."""

    try:
        symbol = str(message["id"]).upper()
        price = float(message["price"])

        raw_time = int(message.get("time", 0))

        # Yahoo peut envoyer des millisecondes au lieu de secondes.
        if raw_time > 10_000_000_000:
            raw_time = raw_time // 1000

        if raw_time > 0:
            timestamp = datetime.fromtimestamp(raw_time, timezone.utc)
        else:
            timestamp = datetime.now(timezone.utc)

        volume = message.get("day_volume")
        if volume is not None:
            volume = int(volume)

    except (KeyError, TypeError, ValueError):
        return None

    if symbol not in TECH_STOCKS or price <= 0:
        return None

    return LiveQuote(
        symbol=symbol,
        price=price,
        timestamp=timestamp,
        day_volume=volume,
    )


async def process_message(message: dict) -> None:
    """Traite chaque nouveau cours reçu."""

    quote = create_quote(message)

    if quote is None:
        return

    current = await get_current_candle(quote.symbol)
    new_candle, finished_candle = update_candle(current, quote)

    if finished_candle is not None:
        await save_candle(finished_candle)

    await save_latest_quote(quote)
    await save_current_candle(new_candle)


async def main() -> None:
    """Charge l'historique puis écoute les nouveaux cours."""

    try:
        number = await backfill_recent_history()
        print(f"{number} bougies historiques enregistrées.")
    except Exception as error:
        print(f"Historique indisponible : {error}")

    websocket = yf.AsyncWebSocket(verbose=False)
    await websocket.subscribe(list(TECH_STOCKS))

    print("Connexion yfinance ouverte.")
    await websocket.listen(process_message)


if __name__ == "__main__":
    asyncio.run(main())
