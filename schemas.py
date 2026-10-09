"""Objets JSON communs, utilisés notamment par l'authentification."""

from datetime import datetime
from typing import Annotated

from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
)


# Règles pour le nom d'utilisateur :
# - 3 à 30 caractères
# - lettres, chiffres, point, tiret et underscore seulement
Username = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=30,
        pattern=r"^[A-Za-z0-9._-]+$",
    ),
]


class DatabaseHealth(BaseModel):
    status: str
    connected: bool
    error: str | None = None


class LiveMarketWorkerHealth(BaseModel):
    status: str
    healthy: bool
    running: bool
    connected: bool
    subscribed_assets: int = 0
    last_heartbeat_at: datetime | None = None
    last_quote_at: datetime | None = None
    quotes_received: int = 0
    live_prices: int = 0
    delayed_prices: int = 0
    unavailable_prices: int = 0
    error: str | None = None


class OrchestratorHealth(BaseModel):
    status: str
    enabled: bool
    running: bool
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    pending_follow_ups: int = 0
    running_follow_ups: int = 0
    error: str | None = None


class PortfolioStrategistHealth(BaseModel):
    strategist_id: int
    portfolio_id: int
    status: str
    running: bool
    last_full_review_at: datetime | None = None
    next_full_review_at: datetime | None = None


class PortfolioStrategistsHealth(BaseModel):
    status: str
    enabled: bool
    running: bool
    active: int = 0
    paused: int = 0
    pending_runs: int = 0
    running_runs: int = 0
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    items: list[PortfolioStrategistHealth] = Field(default_factory=list)
    error: str | None = None


class RSSFeedHealth(BaseModel):
    feed_id: int
    name: str
    status: str
    running: bool
    last_status: str | None = None
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    last_error: str | None = None


class RSSFeedsHealth(BaseModel):
    status: str
    enabled: bool
    running: bool
    active: int = 0
    paused: int = 0
    running_feeds: int = 0
    failed_feeds: int = 0
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    items: list[RSSFeedHealth] = Field(default_factory=list)
    error: str | None = None


class HealthResponse(BaseModel):
    status: str = Field(examples=["ok", "degraded"])
    checked_at: datetime
    database: DatabaseHealth
    live_market_worker: LiveMarketWorkerHealth
    orchestrator: OrchestratorHealth
    portfolio_strategists: PortfolioStrategistsHealth
    rss_feeds: RSSFeedsHealth


class LoginRequest(BaseModel):
    # On laisse volontairement des strings simples ici :
    # un ancien utilisateur ayant le mot de passe "1234"
    # doit encore pouvoir se connecter.
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: Username
    email: EmailStr
    password: str


class UpdatePasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=72)

    @field_validator("new_password")
    @classmethod
    def validate_password_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Le mot de passe ne doit pas dépasser 72 octets.")
        if not any(character in "0123456789" for character in value):
            raise ValueError("Le mot de passe doit contenir au moins un chiffre.")
        return value


class TokenResponse(BaseModel):
    token: str
    message: str


class UserResponse(BaseModel):
    user_id: int
    username: str
    role: str
    balance: float
    email: str 
    is_active : bool 
    created_at : datetime
