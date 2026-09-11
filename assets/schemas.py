"""Formats des données reçues de l'IA ou échangées avec Avalonia.

Pydantic vérifie les types et les contraintes avant d'accepter les données.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class DetectedAsset(BaseModel):
    """Un symbole Yahoo Finance trouvé par DeepSeek."""

    # Field précise les limites : symbole non vide, confiance entre 0 et 100.
    symbol: str = Field(min_length=1, max_length=30)
    confidence: int = Field(ge=0, le=100)
    reason: str


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

    # Les champs spécialisés restent à None s'ils ne concernent pas ce type
    # d'actif. Par exemple, une action n'a pas d'adresse de contrat crypto.
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
    """Prix d'ouverture, plus haut, plus bas, clôture et volume d'un intervalle."""

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
