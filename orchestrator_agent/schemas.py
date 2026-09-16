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


class MemoryState(BaseModel):
    """Small durable state, not an unlimited transcript."""

    version: int = 1
    goals: list[str] = Field(default_factory=list)
    facts: dict[str, Any] = Field(default_factory=dict)
    decisions: list[DecisionRecord] = Field(default_factory=list)
    worker_metrics: dict[str, WorkerMetrics] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=utc_now)
