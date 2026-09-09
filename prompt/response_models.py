"""Validated response shapes returned by the language model."""

from typing import Literal

from pydantic import BaseModel, Field


class ClassificationResult(BaseModel):
    cls_category: str
    cls_importance: str
    cls_sentiment: str
    cls_reason: str
    cls_should_trigger: bool
    niches: list[str] = Field(default_factory=list)


class AnalysisSignalResult(BaseModel):
    sig_asset_symbol: str = Field(min_length=1, max_length=50)
    sig_action: Literal["buy", "sell", "hold"]
    sig_entry_price: float | None = Field(default=None, gt=0)
    sig_stop_loss_price: float | None = Field(default=None, gt=0)
    sig_take_profit_price: float | None = Field(default=None, gt=0)
    sig_confidence: int = Field(ge=0, le=100)
    sig_timeframe: Literal[
        "short-term",
        "medium-term",
        "long-term",
        "multiple",
    ]
    sig_expires_at: None = None


class AssetAnalysisResult(BaseModel):
    symbol: str = Field(min_length=1, max_length=50)
    direction: Literal["negative", "neutral", "positive", "mixed"]
    confidence: int = Field(ge=0, le=100)
    timeframe: Literal[
        "short-term",
        "medium-term",
        "long-term",
        "multiple",
    ]
    reason: str


class FinancialAnalysisResult(BaseModel):
    anl_response_text: str
    anl_summary: str
    anl_direction: Literal["negative", "neutral", "positive", "mixed"]
    anl_market_sentiment: Literal[
        "bearish",
        "neutral",
        "bullish",
        "mixed",
    ]
    anl_confidence: int = Field(ge=0, le=100)
    anl_risk_level: Literal["low", "medium", "high"]
    anl_timeframe: Literal[
        "short-term",
        "medium-term",
        "long-term",
        "multiple",
    ]
    assets: list[AssetAnalysisResult] = Field(default_factory=list)
    signals: list[AnalysisSignalResult] = Field(default_factory=list)
