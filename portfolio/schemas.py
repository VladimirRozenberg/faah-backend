

"""Formats des demandes et des réponses du portefeuille."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


PortfolioStrategyType = Literal[
    "conservative",
    "income",
    "balanced",
    "growth",
    "aggressive",
    "custom",
]
PortfolioAssetType = Literal["stock", "crypto", "forex", "future"]


class PortfolioCreateRequest(BaseModel):
    """Configuration for a new user-owned portfolio and its strategist."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2_000)
    strategy_type: PortfolioStrategyType | None = None
    preferred_asset_types: list[PortfolioAssetType] = Field(
        default_factory=list,
        max_length=4,
    )
    preferred_niche_ids: list[int] = Field(default_factory=list, max_length=100)

    risk_tolerance: Literal["low", "medium", "high"] = "medium"
    max_position_size_pct: float = Field(default=5.0, gt=0, le=100)
    max_open_positions: int = Field(default=10, ge=1, le=1_000)
    # V1 supports USD only. Keeping the field makes future currency expansion
    # backward compatible without suggesting that FX conversion exists today.
    base_currency: Literal["USD"] = "USD"

    @field_validator("preferred_asset_types", "preferred_niche_ids")
    @classmethod
    def preferences_must_be_unique(cls, values: list) -> list:
        if len(values) != len(set(values)):
            raise ValueError("Portfolio preferences cannot contain duplicates.")
        return values

    @field_validator("preferred_niche_ids")
    @classmethod
    def niche_ids_must_be_positive(cls, values: list[int]) -> list[int]:
        if any(value <= 0 for value in values):
            raise ValueError("Preferred niche IDs must be positive.")
        return values


class PortfolioUpdateRequest(BaseModel):
    """Partial portfolio configuration and active-state update."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2_000)
    strategy_type: PortfolioStrategyType | None = None
    preferred_asset_types: list[PortfolioAssetType] | None = Field(
        default=None,
        max_length=4,
    )
    preferred_niche_ids: list[int] | None = Field(default=None, max_length=100)
    risk_tolerance: Literal["low", "medium", "high"] | None = None
    max_position_size_pct: float | None = Field(default=None, gt=0, le=100)
    max_open_positions: int | None = Field(default=None, ge=1, le=1_000)
    base_currency: Literal["USD"] | None = None
    is_active: bool | None = None

    @field_validator("preferred_asset_types", "preferred_niche_ids")
    @classmethod
    def preferences_must_be_unique(cls, values: list | None) -> list | None:
        if values is not None and len(values) != len(set(values)):
            raise ValueError("Portfolio preferences cannot contain duplicates.")
        return values

    @field_validator("preferred_niche_ids")
    @classmethod
    def niche_ids_must_be_positive(
        cls,
        values: list[int] | None,
    ) -> list[int] | None:
        if values is not None and any(value <= 0 for value in values):
            raise ValueError("Preferred niche IDs must be positive.")
        return values


class BuyAssetRequest(BaseModel):
    """Achat simulé envoyé par Avalonia."""

    # Pydantic exige un symbole non vide et des nombres strictement positifs.
    symbol: str = Field(min_length=1)
    quantity: float = Field(gt=0, allow_inf_nan=False)
    purchase_price: float = Field(gt=0, allow_inf_nan=False)


class SellAssetRequest(BaseModel):
    """Vente simulée envoyée par Avalonia."""

    symbol: str = Field(min_length=1)
    quantity: float = Field(gt=0, allow_inf_nan=False)
    sale_price: float = Field(gt=0, allow_inf_nan=False)


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


class UserTransactionResponse(TransactionResponse):
    """A transaction with its owning portfolio identified."""

    portfolio_id: int
    portfolio_name: str


class UserTransactionListResponse(BaseModel):
    """A page of transactions across the authenticated user's portfolios."""

    count: int
    page: int
    page_size: Literal[10] = 10
    total_pages: int
    transactions: list[UserTransactionResponse]


class AssetTransactionSummary(BaseModel):
    asset_id: int
    symbol: str
    name: str
    transaction_count: int
    buy_count: int
    sell_count: int


class TransactionListResponse(BaseModel):
    """Historique des transactions d'un portefeuille."""

    count: int
    transactions: list[TransactionResponse]
    by_asset: list[AssetTransactionSummary]


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
    strategy_type: str | None
    risk_tolerance: str | None
    max_position_size_pct: float | None
    max_open_positions: int | None
    preferred_asset_types: list[PortfolioAssetType]
    preferred_niche_ids: list[int]
    base_currency: str
    is_active: bool
    created_at: datetime
    positions_count: int
    # Montant d'achat des positions encore détenues ; ce n'est pas un solde.
    balance: float
    total_invested: float
    total_current_value: float | None
    total_profit_loss: float | None
    positions: list[PortfolioPositionResponse]


class PortfolioListResponse(BaseModel):
    count: int
    items: list[PortfolioResponse]


class PortfolioSummaryItem(BaseModel):
    portfolio_id: int
    name: str
    description: str | None
    risk_tolerance: Literal["low", "medium", "high", "very_high"] | None
    max_open_positions: int | None
    return_pct: float | None
    base_currency: str
    status: Literal["active", "paused"]


class PortfolioSummaryListResponse(BaseModel):
    count: int
    items: list[PortfolioSummaryItem]


class UserAvailableCashResponse(BaseModel):
    """Available simulated cash held by one user account."""

    user_id: int
    currency: Literal["USD"] = "USD"
    available_cash: float


class UserAssetValueItem(BaseModel):
    """One asset aggregated across all portfolios owned by a user."""

    asset_id: int
    symbol: str
    name: str
    type: str
    portfolios_count: int
    total_quantity: float
    invested_amount: float
    current_price: float | None
    current_value: float | None
    profit_loss: float | None


class UserAssetValueResponse(BaseModel):
    """USD value of every active holding across a user portfolio set."""

    user_id: int
    currency: Literal["USD"] = "USD"
    portfolios_count: int
    assets_count: int
    total_invested: float
    total_current_value: float | None
    total_profit_loss: float | None
    valuation_complete: bool
    missing_price_symbols: list[str]
    assets: list[UserAssetValueItem]
