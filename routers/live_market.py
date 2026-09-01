"""Routes du marché en direct pour le frontend Avalonia."""

import asyncio

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from live_market.candle_builder import public_candle
from live_market.candle_repository import read_candles
from live_market.config import TIMEFRAME
from live_market.redis_client import get_current_candle, get_latest_quote
from live_market.market_schemas import LiveCandleResponse, LiveQuote
from market_data import TECH_STOCKS


router = APIRouter(tags=["Marché en direct"])


def normalize_symbol(symbol: str) -> str:
    """Vérifie que l'action existe dans notre catalogue."""

    symbol = symbol.upper()

    if symbol not in TECH_STOCKS:
        raise HTTPException(status_code=404, detail="Action inconnue.")

    return symbol


@router.get(
    "/api/live/assets/{symbol}/candles",
    response_model=LiveCandleResponse,
)
async def get_live_candles(
    symbol: str,
    limit: int = Query(default=300, ge=1, le=1000),
) -> LiveCandleResponse:
    """Retourne l'historique et ajoute la bougie Redis actuelle."""

    symbol = normalize_symbol(symbol)
    candles = await read_candles(symbol, TIMEFRAME, limit)
    current = await get_current_candle(symbol)

    if current is not None:
        live_candle = public_candle(current)

        if candles and candles[-1].timestamp == live_candle.timestamp:
            # Le volume historique est plus fiable que le volume WebSocket.
            if live_candle.volume == 0 and candles[-1].volume > 0:
                live_candle.volume = candles[-1].volume

            candles[-1] = live_candle
        else:
            candles.append(live_candle)

    candles = candles[-limit:]

    return LiveCandleResponse(
        symbol=symbol,
        timeframe=TIMEFRAME,
        count=len(candles),
        candles=candles,
    )


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
    """Envoie le dernier état Redis à Avalonia toutes les 5 secondes."""

    symbol = symbol.upper()

    if symbol not in TECH_STOCKS:
        await websocket.close(code=1008)
        return

    await websocket.accept()

    try:
        while True:
            latest = await get_latest_quote(symbol)
            current = await get_current_candle(symbol)

            await websocket.send_json(
                {
                    "type": "market_update",
                    "symbol": symbol,
                    "latest": (
                        latest.model_dump(mode="json")
                        if latest is not None
                        else None
                    ),
                    "candle": (
                        public_candle(current).model_dump(mode="json")
                        if current is not None
                        else None
                    ),
                }
            )

            await asyncio.sleep(5)

    except (WebSocketDisconnect, RuntimeError):
        pass
