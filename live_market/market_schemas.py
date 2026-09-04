"""Objets utilisés uniquement par le marché en direct."""

from datetime import datetime

from pydantic import BaseModel


class LiveQuote(BaseModel):
    """Dernier cours reçu depuis yfinance."""

    symbol: str
    price: float
    timestamp: datetime
    day_volume: int | None = None
