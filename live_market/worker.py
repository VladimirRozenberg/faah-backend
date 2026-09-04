"""Reçoit les cours yfinance et garde le dernier prix dans Redis."""

import asyncio
from datetime import datetime, timezone

import yfinance as yf

from assets.catalog import ALL_ASSETS
from live_market.redis_client import save_latest_quote
from live_market.market_schemas import LiveQuote


def create_quote(message: dict) -> LiveQuote | None:
    """Transforme un message yfinance en cours utilisable."""

    try:
        symbol = str(message["id"]).upper()
        price = float(message["price"])

        time_in_ms = int(message.get("time", 0))

        timestamp = datetime.now(timezone.utc)
        if time_in_ms > 0:
            timestamp = datetime.fromtimestamp(
                time_in_ms / 1000,
                timezone.utc,
            )

        raw_volume = message.get("day_volume")
        volume = int(raw_volume) if raw_volume is not None else None

    except (KeyError, TypeError, ValueError):
        return None

    if symbol not in ALL_ASSETS or price <= 0:
        return None

    return LiveQuote(
        symbol=symbol,
        price=price,
        timestamp=timestamp,
        day_volume=volume,
    )


async def process_message(message: dict) -> None:
    """Enregistre le dernier cours reçu dans Redis."""

    quote = create_quote(message)

    if quote is not None:
        await save_latest_quote(quote)


async def main() -> None:
    """Écoute les nouveaux cours sans enregistrer les bougies."""

    websocket = yf.AsyncWebSocket(verbose=False)
    await websocket.subscribe(list(ALL_ASSETS))

    print("Connexion yfinance ouverte.")
    await websocket.listen(process_message)


if __name__ == "__main__":
    asyncio.run(main())
