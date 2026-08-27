"""Modèles JSON échangés entre FastAPI et l'application Avalonia."""

from datetime import datetime

from pydantic import BaseModel, Field


class AssetSummary(BaseModel):
    """Informations affichées dans la liste des actions."""

    symbol: str
    name: str
    exchange: str
    currency: str
    last_price: float
    previous_close: float
    change: float
    change_percent: float
    volume: int | None = None
    retrieved_at: datetime
    source: str = "Yahoo Finance via yfinance"


class AssetListResponse(BaseModel):
    """Réponse de l'endpoint qui retourne les dix actions."""

    count: int
    items: list[AssetSummary]


class Candle(BaseModel):
    """Une bougie OHLCV utilisée pour construire le graphique."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int | None = None


class CandleResponse(BaseModel):
    """Historique d'une action pour une période donnée."""

    symbol: str
    period: str
    interval: str
    count: int
    candles: list[Candle]
    retrieved_at: datetime
    source: str = "Yahoo Finance via yfinance"


class HealthResponse(BaseModel):
    status: str = Field(examples=["ok"])


class StockSyncResponse(BaseModel):
    """Résultat de la synchronisation des actions."""

    created: int
    updated: int
    unchanged: int
    total: int