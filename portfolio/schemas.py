"""Formats des demandes et des réponses du portefeuille."""

from datetime import datetime

from pydantic import BaseModel, Field


class BuyAssetRequest(BaseModel):
    """Achat simulé envoyé par Avalonia."""

    # Pydantic exige un symbole non vide et des nombres strictement positifs.
    symbol: str = Field(min_length=1)
    quantity: float = Field(gt=0)
    purchase_price: float = Field(gt=0)


class SellAssetRequest(BaseModel):
    """Vente simulée envoyée par Avalonia."""

    symbol: str = Field(min_length=1)
    quantity: float = Field(gt=0)
    sale_price: float = Field(gt=0)


class TransactionResponse(BaseModel):
    """Un achat ou une vente enregistré dans PostgreSQL."""

    id: int
    symbol: str
    name: str
    type: str
    quantity: float
    price: float
    fees: float
    currency: str
    amount: float
    created_at: datetime


class TransactionListResponse(BaseModel):
    """Historique des transactions d'un portefeuille."""

    count: int
    transactions: list[TransactionResponse]


class PortfolioPositionResponse(BaseModel):
    """Un actif possédé dans un portefeuille."""

    asset_id: int
    symbol: str
    name: str
    type: str
    quantity: float
    average_purchase_price: float
    invested_amount: float
    # None signifie que le cours n'a pas pu être récupéré dans Redis ou Yahoo.
    current_price: float | None
    current_value: float | None
    profit_loss: float | None
    profit_loss_percent: float | None


class PortfolioResponse(BaseModel):
    """Un portefeuille et toutes ses positions."""

    id: int
    user_id: int
    name: str
    description: str | None
    base_currency: str
    is_active: bool
    created_at: datetime
    positions_count: int
    # Montant d'achat des positions encore détenues ; ce n'est pas un solde.
    total_invested: float
    total_current_value: float | None
    total_profit_loss: float | None
    positions: list[PortfolioPositionResponse]
