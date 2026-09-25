"""Single background service that owns RSS execution and Qwen cycles."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging

from db import AsyncSessionLocal
from orchestrator_agent.brain import LLMOrchestrationBrain
from orchestrator_agent.context import DatabaseContextProvider
from orchestrator_agent.follow_up import (
    FollowUpAnalysisExecutor,
    FollowUpAnalysisRepository,
)
from orchestrator_agent.loop import OrchestrationLoop
from orchestrator_agent.memory import JsonMemoryStore
from orchestrator_agent.orchestrator import Orchestrator
from orchestrator_agent.policy import OrchestratorPolicy
from orchestrator_agent.rss_executor import RSSFeedExecutor
from orchestrator_agent.rss_repository import RSSFeedRepository


logger = logging.getLogger(__name__)
IDLE_WAKE_SECONDS = 60
ERROR_RETRY_BASE_SECONDS = 5
ERROR_RETRY_MAX_SECONDS = 60


def _retry_delay(consecutive_failures: int) -> int:
    """Return a bounded exponential delay for unexpected service failures."""

    exponent = min(4, max(0, consecutive_failures - 1))
    return min(
        ERROR_RETRY_MAX_SECONDS,
        ERROR_RETRY_BASE_SECONDS * (2**exponent),
    )


def _next_orchestration_at(memory: JsonMemoryStore) -> datetime:
    persisted_state = memory.load()
    if persisted_state.cycles:
        previous_cycle = persisted_state.cycles[-1]
        return previous_cycle.started_at + timedelta(
            seconds=previous_cycle.next_run_in_seconds
        )
    return datetime.now(timezone.utc)


async def _run_service_pass(
    memory: JsonMemoryStore,
    next_orchestration_at: datetime,
) -> datetime:
    """Run one service pass and return the next orchestration deadline."""

    async with AsyncSessionLocal() as db:
        follow_up_executions = await FollowUpAnalysisExecutor(
            FollowUpAnalysisRepository(db)
        ).run_pending()
        if follow_up_executions:
            logger.info(
                "Orchestrator executed %d follow-up analysis job(s)",
                follow_up_executions,
            )

    async with AsyncSessionLocal() as db:
        feed_repository = RSSFeedRepository(db)
        executions = await RSSFeedExecutor(feed_repository).run_due()
        if executions:
            logger.info("Orchestrator executed %d due RSS feed(s)", executions)

    now = datetime.now(timezone.utc)
    if now >= next_orchestration_at:
        async with AsyncSessionLocal() as db:
            feed_repository = RSSFeedRepository(db)
            allowed_feeds = await feed_repository.allowed_feed_names()
            orchestrator = Orchestrator(
                policy=OrchestratorPolicy(allowed_feeds=allowed_feeds),
                memory=memory,
                bus=feed_repository,
            )
            result = await OrchestrationLoop(
                orchestrator,
                DatabaseContextProvider(db),
                LLMOrchestrationBrain(db),
                feed_state_provider=feed_repository,
                follow_up_repository=FollowUpAnalysisRepository(db),
            ).run_once(now)
            next_orchestration_at = now + timedelta(
                seconds=result.decision.next_run_in_seconds
            )
            logger.info(
                "Orchestration complete: signals=%d approved=%d "
                "rejected=%d next_run=%s",
                len(result.context.signals),
                len(result.approved_instructions),
                result.rejected_rss_proposals,
                next_orchestration_at.isoformat(),
            )

    async with AsyncSessionLocal() as db:
        next_feed_at = await RSSFeedRepository(db).next_due_at()

    now = datetime.now(timezone.utc)
    wake_at = next_orchestration_at
    if next_feed_at is not None:
        wake_at = min(wake_at, next_feed_at)
    sleep_seconds = max(
        0.25,
        min(IDLE_WAKE_SECONDS, (wake_at - now).total_seconds()),
    )
    await asyncio.sleep(sleep_seconds)
    return next_orchestration_at


async def run_orchestrator_service() -> None:
    """Run due feeds and invoke Qwen on its model-selected cadence."""

    logger.info("Orchestrator service started")
    memory = JsonMemoryStore()
    next_orchestration_at: datetime | None = None
    consecutive_failures = 0
    try:
        while True:
            try:
                if next_orchestration_at is None:
                    next_orchestration_at = _next_orchestration_at(memory)
                next_orchestration_at = await _run_service_pass(
                    memory,
                    next_orchestration_at,
                )
                consecutive_failures = 0
            except asyncio.CancelledError:
                raise
            except Exception:
                consecutive_failures += 1
                delay = _retry_delay(consecutive_failures)
                logger.exception(
                    "Unexpected orchestrator service error; retrying in %d seconds",
                    delay,
                )
                await asyncio.sleep(delay)
    finally:
        logger.info("Orchestrator service stopped")
