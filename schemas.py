"""Modèles JSON échangés entre FastAPI et l'application Avalonia."""

from datetime import datetime

from pydantic import BaseModel, Field


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
    is_active: bool
    created_at: datetime

    # Informations d'une action.
    exchange: str | None = None
    sector: str | None = None
    industry: str | None = None

    # Informations d'une cryptomonnaie.
    blockchain: str | None = None
    contract_address: str | None = None

    # Informations d'une paire Forex.
    base_currency: str | None = None
    quote_currency: str | None = None

    # Informations d'une matière première.
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


class HealthResponse(BaseModel):
    status: str = Field(examples=["ok"])


class AssetSyncResponse(BaseModel):
    """Résultat de la synchronisation du catalogue d'actifs."""

    created: int
    updated: int
    unchanged: int
    unavailable: int
    total: int

class LoginRequest(BaseModel):
    username: str
    password: str
 
 
class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str
 
 
class TokenResponse(BaseModel):
    token: str
    message: str
 
 
class UserResponse(BaseModel):
    user_id: int
    username: str
    role: str
 
