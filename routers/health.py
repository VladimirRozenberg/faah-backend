"""Operational health and scheduling visibility for background services."""

from datetime import datetime, timedelta, timezone
import os

from fastapi import APIRouter, Request
from sqlalchemy import func, select, text

from db import DbSession
from models import (
    OrchestratorAnalysisJob,
    PortfolioStrategist,
    PortfolioStrategistRun,
    RSSFeed,
    RSSFeedRun,
)
from orchestrator_agent.memory import JsonMemoryStore
from schemas import (
    DatabaseHealth,
    HealthResponse,
    OrchestratorHealth,
    PortfolioStrategistHealth,
    PortfolioStrategistsHealth,
    RSSFeedHealth,
    RSSFeedsHealth,
)


router = APIRouter(tags=["Système"])


def _configured(name: str) -> bool:
    return os.getenv(name, "false").lower() == "true"


def _task_running(request: Request, name: str) -> bool:
    tasks = getattr(request.app.state, "background_tasks", [])
    return any(task.get_name() == name and not task.done() for task in tasks)


def _service_status(enabled: bool, running: bool, degraded: bool = False) -> str:
    if not enabled:
        return "disabled"
    if not running:
        return "down"
    return "degraded" if degraded else "running"


@router.get("/health", response_model=HealthResponse)
async def health(request: Request, db: DbSession) -> HealthResponse:
    """Report API dependencies, worker liveness, queues, and schedules."""

    checked_at = datetime.now(timezone.utc)
    orchestrator_enabled = _configured("RUN_ORCHESTRATOR")
    strategists_enabled = _configured("RUN_STRATEGISTS")
    orchestrator_running = _task_running(request, "faah-orchestrator")
    strategists_running = _task_running(request, "faah-portfolio-strategists")

    last_orchestration_at = None
    next_orchestration_at = None
    memory_error = None
    try:
        memory = JsonMemoryStore().load()
        last_orchestration_at = memory.last_cycle_at
        if memory.cycles:
            latest_cycle = memory.cycles[-1]
            next_orchestration_at = latest_cycle.started_at + timedelta(
                seconds=latest_cycle.next_run_in_seconds
            )
        elif orchestrator_running:
            next_orchestration_at = checked_at
    except Exception as exc:
        memory_error = f"Orchestrator memory unavailable ({type(exc).__name__})"

    database = DatabaseHealth(status="connected", connected=True)
    try:
        await db.execute(text("SELECT 1"))

        pending_follow_ups = int(
            await db.scalar(
                select(func.count(OrchestratorAnalysisJob.oaj_id)).where(
                    OrchestratorAnalysisJob.oaj_status == "pending"
                )
            )
            or 0
        )
        running_follow_ups = int(
            await db.scalar(
                select(func.count(OrchestratorAnalysisJob.oaj_id)).where(
                    OrchestratorAnalysisJob.oaj_status == "running"
                )
            )
            or 0
        )

        strategists = list(
            (
                await db.scalars(
                    select(PortfolioStrategist).order_by(
                        PortfolioStrategist.pst_id
                    )
                )
            ).all()
        )
        running_strategist_ids = set(
            (
                await db.scalars(
                    select(PortfolioStrategistRun.psr_pst_id).where(
                        PortfolioStrategistRun.psr_status == "running"
                    )
                )
            ).all()
        )
        pending_strategist_runs = int(
            await db.scalar(
                select(func.count(PortfolioStrategistRun.psr_id)).where(
                    PortfolioStrategistRun.psr_status == "pending"
                )
            )
            or 0
        )
        running_strategist_runs = int(
            await db.scalar(
                select(func.count(PortfolioStrategistRun.psr_id)).where(
                    PortfolioStrategistRun.psr_status == "running"
                )
            )
            or 0
        )
        last_strategist_run_at = await db.scalar(
            select(func.max(PortfolioStrategistRun.psr_completed_at))
        )
        strategist_items = [
            PortfolioStrategistHealth(
                strategist_id=item.pst_id,
                portfolio_id=item.pst_prt_id,
                status=item.pst_status,
                running=item.pst_id in running_strategist_ids,
                last_full_review_at=item.pst_last_full_review_at,
                next_full_review_at=item.pst_next_full_review_at,
            )
            for item in strategists
        ]
        next_full_review_at = min(
            (
                item.pst_next_full_review_at
                for item in strategists
                if item.pst_status == "active"
            ),
            default=None,
        )
        next_strategist_run_at = (
            checked_at
            if pending_strategist_runs or running_strategist_runs
            else next_full_review_at
        )

        feeds = list(
            (await db.scalars(select(RSSFeed).order_by(RSSFeed.rsf_name))).all()
        )
        running_feed_ids = set(
            (
                await db.scalars(
                    select(RSSFeedRun.rfr_rsf_id).where(
                        RSSFeedRun.rfr_status == "running"
                    )
                )
            ).all()
        )
        feed_items = [
            RSSFeedHealth(
                feed_id=feed.rsf_id,
                name=feed.rsf_name,
                status=feed.rsf_status,
                running=feed.rsf_id in running_feed_ids,
                last_status=feed.rsf_last_status,
                last_run_at=feed.rsf_last_polled_at,
                next_run_at=feed.rsf_next_poll_at,
                last_error=feed.rsf_last_error,
            )
            for feed in feeds
        ]
        failed_feeds = sum(feed.rsf_last_status == "failed" for feed in feeds)
        next_feed_run_at = min(
            (
                feed.rsf_next_poll_at
                for feed in feeds
                if feed.rsf_next_poll_at is not None
                and (
                    feed.rsf_status == "active"
                    or feed.rsf_next_poll_trigger == "run_now"
                )
            ),
            default=None,
        )
        last_feed_run_at = max(
            (
                feed.rsf_last_polled_at
                for feed in feeds
                if feed.rsf_last_polled_at is not None
            ),
            default=None,
        )
    except Exception as exc:
        error = f"Database unavailable ({type(exc).__name__})"
        database = DatabaseHealth(status="unavailable", connected=False, error=error)
        pending_follow_ups = 0
        running_follow_ups = 0
        strategist_items = []
        pending_strategist_runs = 0
        running_strategist_runs = 0
        last_strategist_run_at = None
        next_strategist_run_at = None
        feed_items = []
        failed_feeds = 0
        last_feed_run_at = None
        next_feed_run_at = None

    orchestrator = OrchestratorHealth(
        status=_service_status(
            orchestrator_enabled,
            orchestrator_running,
            memory_error is not None or not database.connected,
        ),
        enabled=orchestrator_enabled,
        running=orchestrator_running,
        last_run_at=last_orchestration_at,
        next_run_at=next_orchestration_at,
        pending_follow_ups=pending_follow_ups,
        running_follow_ups=running_follow_ups,
        error=memory_error or database.error,
    )
    portfolio_strategists = PortfolioStrategistsHealth(
        status=_service_status(
            strategists_enabled,
            strategists_running,
            not database.connected,
        ),
        enabled=strategists_enabled,
        running=strategists_running,
        active=sum(item.status == "active" for item in strategist_items),
        paused=sum(item.status == "paused" for item in strategist_items),
        pending_runs=pending_strategist_runs,
        running_runs=running_strategist_runs,
        last_run_at=last_strategist_run_at,
        next_run_at=next_strategist_run_at,
        items=strategist_items,
        error=database.error,
    )
    rss_feeds = RSSFeedsHealth(
        status=_service_status(
            orchestrator_enabled,
            orchestrator_running,
            not database.connected or failed_feeds > 0,
        ),
        enabled=orchestrator_enabled,
        running=orchestrator_running,
        active=sum(item.status == "active" for item in feed_items),
        paused=sum(item.status == "paused" for item in feed_items),
        running_feeds=sum(item.running for item in feed_items),
        failed_feeds=failed_feeds,
        last_run_at=last_feed_run_at,
        next_run_at=next_feed_run_at,
        items=feed_items,
        error=database.error,
    )
    components = (orchestrator, portfolio_strategists, rss_feeds)
    overall_status = (
        "ok"
        if database.connected
        and all(item.status not in {"down", "degraded"} for item in components)
        else "degraded"
    )

    return HealthResponse(
        status=overall_status,
        checked_at=checked_at,
        database=database,
        orchestrator=orchestrator,
        portfolio_strategists=portfolio_strategists,
        rss_feeds=rss_feeds,
    )
