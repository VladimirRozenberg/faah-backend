"""Format d'un cours en direct."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class LiveQuote(BaseModel):
    """Dernier cours reçu depuis yfinance."""

    # Pydantic vérifie le format des données. Le volume peut être absent.
    symbol: str
    price: float
    timestamp: datetime
    source: Literal["live", "daily"] = "live"
    day_volume: int | None = None
    previous_close: float | None = None
    change: float | None = None
    change_percent: float | None = None


class LiveWorkerStatus(BaseModel):
    """Short-lived worker heartbeat shared with the API through Redis."""

    running: bool
    connected: bool
    subscribed_assets: int
    last_heartbeat_at: datetime
    last_quote_at: datetime | None = None
    quotes_received: int = 0
    live_prices: int = 0
    delayed_prices: int = 0
    unavailable_prices: int = 0
    error: str | None = None
