"""Validated messages exchanged by the orchestrator and workers."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ActionType(str, Enum):
    SET_RSS_INTERVAL = "set_rss_interval"
    RUN_RSS_NOW = "run_rss_now"
    PAUSE_RSS = "pause_rss"
    RESUME_RSS = "resume_rss"


class DecisionProposal(BaseModel):
    """What the AI wants to do. A proposal has no authority by itself."""

    action: ActionType
    target: str = Field(min_length=1, max_length=200)
    parameters: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=2_000)
    confidence: float = Field(ge=0.0, le=1.0)


class Instruction(BaseModel):
    """A proposal that passed the deterministic policy gate."""

    instruction_id: str = Field(default_factory=lambda: str(uuid4()))
    action: ActionType
    target: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    reason: str
    confidence: float
    created_at: datetime = Field(default_factory=utc_now)


class DecisionRecord(BaseModel):
    proposal: DecisionProposal
    approved: bool
    rejection_reason: str | None = None
    instruction_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class WorkerReport(BaseModel):
    """Feedback used to measure whether an instruction helped."""

    worker: str = Field(min_length=1, max_length=200)
    instruction_id: str | None = None
    success: bool
    duration_ms: int = Field(ge=0)
    items_processed: int = Field(default=0, ge=0)
    error: str | None = Field(default=None, max_length=2_000)
    created_at: datetime = Field(default_factory=utc_now)


class WorkerMetrics(BaseModel):
    runs: int = 0
    successes: int = 0
    failures: int = 0
    items_processed: int = 0
    total_duration_ms: int = 0


class RSSFeedState(BaseModel):
    feed_id: int
    name: str
    url: str
    source_prefix: str
    poll_interval_seconds: int
    status: str
    last_polled_at: datetime | None = None
    next_poll_at: datetime | None = None
    next_poll_trigger: str
    pending_instruction_id: str | None = None
    last_status: str | None = None
    last_items_processed: int
    last_error: str | None = None
    updated_at: datetime


class RSSFeedRunState(BaseModel):
    run_id: int
    feed_id: int
    feed_name: str
    trigger: str
    instruction_id: str | None = None
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    items_processed: int
    error: str | None = None


class SignalSnapshot(BaseModel):
    """The small, model-facing representation of a trading signal."""

    signal_id: int
    analysis_id: int
    asset_id: int
    asset_symbol: str
    action: str
    confidence: int | None = None
    timeframe: str | None = None
    status: str | None = None
    created_at: datetime
    generating_analysis_summary: str | None = None


class AnalysisSummary(BaseModel):
    """A prior analysis for an asset involved in the current signal batch."""

    analysis_id: int
    asset_id: int
    asset_symbol: str
    summary: str
    direction: str | None = None
    confidence: int | None = None
    risk_level: str | None = None
    timeframe: str | None = None
    created_at: datetime


class AnalysisFollowUp(BaseModel):
    """A targeted research gap found by the orchestrator."""

    asset_symbol: str = Field(min_length=1, max_length=50)
    question: str = Field(min_length=1, max_length=2_000)
    reason: str = Field(min_length=1, max_length=2_000)
    priority: int = Field(ge=1, le=5)


class AnalysisFollowUpJobState(BaseModel):
    """Persisted state and result of one targeted follow-up request."""

    job_id: int
    asset_id: int
    asset_symbol: str
    question: str
    reason: str
    priority: int
    status: str
    result_analysis_id: int | None = None
    result_summary: str | None = None
    result_text: str | None = None
    error: str | None = None
    requested_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class CycleContext(BaseModel):
    started_at: datetime
    signal_window_start: datetime
    previous_instructions: str
    signals: list[SignalSnapshot] = Field(default_factory=list)
    analysis_history: list[AnalysisSummary] = Field(default_factory=list)
    follow_up_jobs: list[AnalysisFollowUpJobState] = Field(default_factory=list)
    allowed_rss_feeds: list[str] = Field(default_factory=list)
    rss_feed_states: list[RSSFeedState] = Field(default_factory=list)


class CycleDecision(BaseModel):
    """Structured judgment returned by the orchestration brain."""

    situation_summary: str = Field(min_length=1, max_length=4_000)
    follow_up_analysis: list[AnalysisFollowUp] = Field(
        default_factory=list,
        max_length=20,
    )
    rss_proposals: list[DecisionProposal] = Field(
        default_factory=list,
        max_length=50,
    )
    next_instructions: str = Field(min_length=1, max_length=4_000)
    next_run_in_seconds: int = Field(
        ge=300,
        le=7_200,
        description=(
            "Delay before the next orchestrator cycle: 300 seconds (5 minutes) "
            "through 7200 seconds (2 hours)."
        ),
    )


class BrainResult(BaseModel):
    """Validated judgment plus the complete upstream model response."""

    decision: CycleDecision
    model: str
    raw_content: str
    provider_response: dict[str, Any]


class CycleRecord(BaseModel):
    started_at: datetime
    signal_window_start: datetime
    signal_ids: list[int] = Field(default_factory=list)
    situation_summary: str
    follow_up_analysis: list[AnalysisFollowUp] = Field(default_factory=list)
    created_follow_up_job_ids: list[int] = Field(default_factory=list)
    approved_instruction_ids: list[str] = Field(default_factory=list)
    rejected_rss_proposals: int = 0
    next_instructions: str
    # The default keeps memory written by the earlier prototype readable.
    next_run_in_seconds: int = Field(default=3_600, ge=300, le=7_200)


class CycleResult(BaseModel):
    context: CycleContext
    decision: CycleDecision
    model: str
    raw_model_content: str
    complete_model_response: dict[str, Any]
    created_follow_up_jobs: list[AnalysisFollowUpJobState] = Field(
        default_factory=list
    )
    approved_instructions: list[Instruction] = Field(default_factory=list)
    rejected_rss_proposals: int = 0


class MemoryState(BaseModel):
    """Small durable state, not an unlimited transcript."""

    version: int = 1
    goals: list[str] = Field(default_factory=list)
    facts: dict[str, Any] = Field(default_factory=dict)
    decisions: list[DecisionRecord] = Field(default_factory=list)
    worker_metrics: dict[str, WorkerMetrics] = Field(default_factory=dict)
    last_cycle_at: datetime | None = None
    next_instructions: str | None = None
    cycles: list[CycleRecord] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utc_now)
