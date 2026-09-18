"""Swagger-visible endpoint for running one real orchestration cycle."""

from datetime import datetime, timezone
import os
from pathlib import Path

from fastapi import APIRouter, Query

from db import DbSession
from orchestrator_agent.brain import LLMOrchestrationBrain
from orchestrator_agent.context import DatabaseContextProvider
from orchestrator_agent.follow_up import FollowUpAnalysisRepository
from orchestrator_agent.loop import OrchestrationLoop
from orchestrator_agent.memory import JsonMemoryStore
from orchestrator_agent.orchestrator import Orchestrator
from orchestrator_agent.policy import OrchestratorPolicy
from orchestrator_agent.rss_repository import RSSFeedRepository
from orchestrator_agent.schemas import (
    AnalysisFollowUpJobState,
    CycleResult,
    RSSFeedRunState,
    RSSFeedState,
)


router = APIRouter(prefix="/api/orchestrator", tags=["Orchestrator prototype"])

DEFAULT_TEST_MEMORY_PATH = "data/orchestrator_swagger_memory.json"


@router.get("/rss-feeds", response_model=list[RSSFeedState])
async def list_rss_feed_schedules(db: DbSession) -> list[RSSFeedState]:
    """Expose PostgreSQL-owned RSS configuration and scheduler state."""

    return await RSSFeedRepository(db).feed_states()


@router.get("/rss-feed-runs", response_model=list[RSSFeedRunState])
async def list_rss_feed_runs(
    db: DbSession,
    feed_name: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[RSSFeedRunState]:
    """Expose the persisted execution history for scheduler observability."""

    rows = await RSSFeedRepository(db).list_runs(
        feed_name=feed_name,
        limit=limit,
    )
    return [
        RSSFeedRunState(
            run_id=run.rfr_id,
            feed_id=run.rfr_rsf_id,
            feed_name=name,
            trigger=run.rfr_trigger,
            instruction_id=run.rfr_instruction_id,
            status=run.rfr_status,
            started_at=run.rfr_started_at,
            completed_at=run.rfr_completed_at,
            items_processed=run.rfr_items_processed,
            error=run.rfr_error,
        )
        for run, name in rows
    ]


@router.get(
    "/analysis-jobs",
    response_model=list[AnalysisFollowUpJobState],
)
async def list_analysis_jobs(
    db: DbSession,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AnalysisFollowUpJobState]:
    """Expose pending, completed and failed orchestrator follow-up work."""

    return await FollowUpAnalysisRepository(db).list_states(limit=limit)


@router.post("/test-run", response_model=CycleResult)
async def run_test_orchestration(
    db: DbSession,
    reset_memory: bool = Query(
        default=False,
        description="Start with the hardcoded first-run instructions.",
    ),
) -> CycleResult:
    """Run Qwen against current database signals and return its full response."""

    memory_path = Path(
        os.getenv("ORCHESTRATOR_TEST_MEMORY_PATH", DEFAULT_TEST_MEMORY_PATH)
    )
    if reset_memory and memory_path.exists():
        memory_path.unlink()

    now = datetime.now(timezone.utc)
    feed_repository = RSSFeedRepository(db)
    allowed_feeds = await feed_repository.allowed_feed_names()
    agent = Orchestrator(
        policy=OrchestratorPolicy(
            allowed_feeds=allowed_feeds,
        ),
        memory=JsonMemoryStore(memory_path),
        bus=feed_repository,
    )
    return await OrchestrationLoop(
        agent,
        DatabaseContextProvider(db),
        LLMOrchestrationBrain(),
        feed_state_provider=feed_repository,
        follow_up_repository=FollowUpAnalysisRepository(db),
    ).run_once(now)
