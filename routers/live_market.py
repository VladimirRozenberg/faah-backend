"""Routes du marché en direct pour le frontend Avalonia."""

import asyncio

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from db import DbSession
from live_market.redis_client import get_latest_quote
from live_market.market_schemas import LiveQuote
from models import Asset


router = APIRouter(tags=["Marché en direct"])


async def find_tracked_symbol(db: DbSession, symbol: str) -> str | None:
    """Vérifie que l'actif existe et doit être suivi."""

    symbol = symbol.upper()
    asset = await db.scalar(
        select(Asset).where(
            Asset.ast_symbol == symbol,
            Asset.ast_is_tracked.is_(True),
        )
    )
    return symbol if asset is not None else None


@router.get(
    "/api/live/assets/{symbol}/latest",
    response_model=LiveQuote,
)
async def get_latest_price(symbol: str, db: DbSession) -> LiveQuote:
    """Retourne le dernier cours enregistré dans Redis."""

    symbol = await find_tracked_symbol(db, symbol)

    if symbol is None:
        raise HTTPException(status_code=404, detail="Actif inconnu.")

    quote = await get_latest_quote(symbol)

    if quote is None:
        raise HTTPException(
            status_code=404,
            detail="Aucun cours en direct reçu pour le moment.",
        )

    return quote


@router.websocket("/ws/market/{symbol}")
async def market_websocket(
    websocket: WebSocket,
    symbol: str,
    db: DbSession,
) -> None:
    """Envoie le dernier cours Redis à Avalonia toutes les 3 secondes."""

    symbol = await find_tracked_symbol(db, symbol)

    if symbol is None:
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
