"""Validated inputs and decisions for portfolio strategists."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from orchestrator_agent.schemas import AnalysisFollowUp


class PriceMovement(BaseModel):
    symbol: str
    event_type: Literal["price_rise", "price_drop"]
    price_before: float = Field(gt=0)
    price_after: float = Field(gt=0)
    change_pct: float
    window_seconds: int = Field(gt=0)
    detected_at: datetime


class StrategistPosition(BaseModel):
    asset_id: int
    symbol: str
    name: str
    asset_type: str
    quantity: float
    average_purchase_price: float
    current_price: float | None = None


class StrategistSignal(BaseModel):
    signal_id: int
    analysis_id: int
    asset_id: int
    asset_symbol: str
    action: str
    confidence: int | None = None
    timeframe: str | None = None
    status: str | None = None
    created_at: datetime
    analysis_summary: str | None = None
    analysis_risk_level: str | None = None


class StrategistAnalysis(BaseModel):
    analysis_id: int
    asset_id: int | None = None
    asset_symbol: str | None = None
    trigger_type: str
    summary: str | None = None
    direction: str | None = None
    confidence: int | None = None
    risk_level: str | None = None
    timeframe: str | None = None
    created_at: datetime


class StrategistContext(BaseModel):
    review_type: Literal["targeted_signal", "targeted_price", "full"]
    reason: str
    portfolio: dict[str, Any]
    instructions: str | None = None
    positions: list[StrategistPosition] = Field(default_factory=list)
    triggering_signal: StrategistSignal | None = None
    triggering_market_event: dict[str, Any] | None = None
    recent_signals: list[StrategistSignal] = Field(default_factory=list)
    analyses: list[StrategistAnalysis] = Field(default_factory=list)
    recent_follow_up_jobs: list[dict[str, Any]] = Field(default_factory=list)
    recent_strategist_ideas: list[dict[str, Any]] = Field(default_factory=list)


class HoldingAssessment(BaseModel):
    asset_symbol: str = Field(min_length=1, max_length=50)
    verdict: Literal["good", "bad", "watch", "unchanged"]
    reason: str = Field(min_length=1, max_length=2_000)


class StrategistOpportunity(BaseModel):
    asset_symbol: str = Field(min_length=1, max_length=50)
    signal_id: int | None = None
    reason: str = Field(min_length=1, max_length=2_000)
    confidence: int = Field(ge=0, le=100)


class StrategistReviewDecision(BaseModel):
    summary: str = Field(min_length=1, max_length=4_000)
    portfolio_health: Literal["good", "stable", "watch", "concern"]
    targeted_conclusion: Literal[
        "no_action",
        "watch",
        "opportunity",
        "warning",
        "follow_up",
    ] | None = None
    targeted_reason: str | None = Field(default=None, min_length=1, max_length=2_000)
    holding_assessments: list[HoldingAssessment] = Field(
        default_factory=list,
        max_length=100,
    )
    opportunities: list[StrategistOpportunity] = Field(
        default_factory=list,
        max_length=50,
    )
    follow_up_analysis: list[AnalysisFollowUp] = Field(
        default_factory=list,
        max_length=10,
    )
    escalate_to_full_review: bool = False
    next_review_notes: str = Field(
        default="Recheck this portfolio at the next scheduled full review.",
        min_length=1,
        max_length=4_000,
    )


class StrategistBrainResult(BaseModel):
    decision: StrategistReviewDecision
    model: str
    raw_content: str
    provider_response: dict[str, Any]
    system_instructions: str
    user_prompt: str
