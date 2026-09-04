"""Routes du marché en direct pour le frontend Avalonia."""

import asyncio

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from assets.catalog import ALL_ASSETS
from live_market.redis_client import get_latest_quote
from live_market.market_schemas import LiveQuote


router = APIRouter(tags=["Marché en direct"])


def normalize_symbol(symbol: str) -> str:
    """Vérifie que l'actif existe dans notre catalogue."""

    symbol = symbol.upper()

    if symbol not in ALL_ASSETS:
        raise HTTPException(status_code=404, detail="Actif inconnu.")

    return symbol


@router.get(
    "/api/live/assets/{symbol}/latest",
    response_model=LiveQuote,
)
async def get_latest_price(symbol: str) -> LiveQuote:
    """Retourne le dernier cours enregistré dans Redis."""

    symbol = normalize_symbol(symbol)
    quote = await get_latest_quote(symbol)

    if quote is None:
        raise HTTPException(
            status_code=404,
            detail="Aucun cours en direct reçu pour le moment.",
        )

    return quote


@router.websocket("/ws/market/{symbol}")
async def market_websocket(websocket: WebSocket, symbol: str) -> None:
    """Envoie le dernier cours Redis à Avalonia toutes les 3 secondes."""

    symbol = symbol.upper()

    if symbol not in ALL_ASSETS:
        await websocket.close(code=1008)
        return

    await websocket.accept()

    try:
        while True:
            latest = await get_latest_quote(symbol)
            await websocket.send_json(
                {
                    "type": "market_update",
                    "symbol": symbol,
                    "latest": (
                        latest.model_dump(mode="json")
                        if latest is not None
                        else None
                    ),
                }
            )

            await asyncio.sleep(3)

    except (WebSocketDisconnect, RuntimeError):
        pass
