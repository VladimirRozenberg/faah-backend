"""Format d'un cours en direct."""

from datetime import datetime

from pydantic import BaseModel


class LiveQuote(BaseModel):
    """Dernier cours reçu depuis yfinance."""

    # Pydantic vérifie le format des données. Le volume peut être absent.
    symbol: str
    price: float
    timestamp: datetime
    day_volume: int | None = None


class LiveWorkerStatus(BaseModel):
    """Short-lived worker heartbeat shared with the API through Redis."""

    running: bool
    connected: bool
    subscribed_assets: int
    last_heartbeat_at: datetime
    error: str | None = None
