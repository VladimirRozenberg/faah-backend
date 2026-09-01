"""Objets utilisés uniquement par le marché en direct."""

from datetime import datetime

from pydantic import BaseModel


class LiveQuote(BaseModel):
    """Dernier cours reçu depuis yfinance."""

    symbol: str
    price: float
    timestamp: datetime
    day_volume: int | None = None


class LiveCandle(BaseModel):
    """Bougie OHLCV d'une minute."""

    symbol: str
    timeframe: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int = 0


class CandleState(LiveCandle):
    """Bougie Redis avec le dernier volume journalier connu."""

    last_day_volume: int | None = None


class LiveCandleResponse(BaseModel):
    """Réponse envoyée par la nouvelle route d'historique."""

    symbol: str
    timeframe: str
    count: int
    candles: list[LiveCandle]
