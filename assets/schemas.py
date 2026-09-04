"""Objets JSON liés aux actifs et échangés avec Avalonia."""

from datetime import datetime

from pydantic import BaseModel


class AssetSummary(BaseModel):
    """Prix et variation d'un actif provenant de yfinance."""

    symbol: str
    name: str
    type: str
    exchange: str | None = None
    currency: str
    last_price: float
    previous_close: float
    change: float
    change_percent: float
    volume: int | None = None
    retrieved_at: datetime
    source: str = "Yahoo Finance via yfinance"


class MarketListResponse(BaseModel):
    """Prix des actifs disponibles dans le marché."""

    count: int
    items: list[AssetSummary]


class AssetItem(BaseModel):
    """Informations générales et spécialisées d'un actif."""

    id: int
    symbol: str
    name: str
    type: str
    yahoo_type: str | None
    exchange: str | None = None
    currency: str | None = None
    country: str | None = None
    is_tracked: bool
    created_at: datetime
    updated_at: datetime

    sector: str | None = None
    industry: str | None = None

    blockchain: str | None = None
    contract_address: str | None = None

    base_currency: str | None = None
    quote_currency: str | None = None

    underlying_name: str | None = None
    underlying_type: str | None = None
    unit: str | None = None
    contract_size: float | None = None


class AssetListResponse(BaseModel):
    """Liste des actifs enregistrés dans PostgreSQL."""

    count: int
    items: list[AssetItem]


class Candle(BaseModel):
    """Une bougie OHLCV utilisée pour construire le graphique."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int | None = None


class CandleResponse(BaseModel):
    """Historique d'un actif pour une période donnée."""

    symbol: str
    period: str
    interval: str
    count: int
    candles: list[Candle]
    retrieved_at: datetime
    source: str = "Yahoo Finance via yfinance"


class AssetSyncResponse(BaseModel):
    """Résultat de la synchronisation du catalogue d'actifs."""

    created: int
    updated: int
    unchanged: int
    unavailable: int
    total: int
