"""PostgreSQL-backed RSS configuration, scheduling and execution history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import RSSFeed, RSSFeedRun
from orchestrator_agent.schemas import ActionType, Instruction, RSSFeedState


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ClaimedFeed:
    feed: RSSFeed
    run: RSSFeedRun


class RSSFeedRepository:
    """The only component allowed to mutate persisted RSS scheduling state."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_feeds(self) -> list[RSSFeed]:
        return list(
            (
                await self.session.scalars(
                    select(RSSFeed).order_by(RSSFeed.rsf_name)
                )
            ).all()
        )

    async def feed_states(self) -> list[RSSFeedState]:
        return [
            RSSFeedState(
                feed_id=feed.rsf_id,
                name=feed.rsf_name,
                url=feed.rsf_url,
                source_prefix=feed.rsf_source_prefix,
                poll_interval_seconds=feed.rsf_poll_interval_seconds,
                status=feed.rsf_status,
                last_polled_at=feed.rsf_last_polled_at,
                next_poll_at=feed.rsf_next_poll_at,
                next_poll_trigger=feed.rsf_next_poll_trigger,
                pending_instruction_id=feed.rsf_pending_instruction_id,
                last_status=feed.rsf_last_status,
                last_items_processed=feed.rsf_last_items_processed,
                last_error=feed.rsf_last_error,
                updated_at=feed.rsf_updated_at,
            )
            for feed in await self.list_feeds()
        ]

    async def allowed_feed_names(self) -> frozenset[str]:
        names = await self.session.scalars(select(RSSFeed.rsf_name))
        return frozenset(names.all())

    async def list_runs(
        self,
        *,
        feed_name: str | None = None,
        limit: int = 100,
    ) -> list[tuple[RSSFeedRun, str]]:
        statement = (
            select(RSSFeedRun, RSSFeed.rsf_name)
            .join(RSSFeed, RSSFeed.rsf_id == RSSFeedRun.rfr_rsf_id)
            .order_by(RSSFeedRun.rfr_started_at.desc(), RSSFeedRun.rfr_id.desc())
            .limit(limit)
        )
        if feed_name is not None:
            statement = statement.where(RSSFeed.rsf_name == feed_name)
        return list((await self.session.execute(statement)).all())

    async def publish(self, instruction: Instruction) -> None:
        """Apply one policy-approved instruction to the database schedule."""

        feed = await self.session.scalar(
            select(RSSFeed)
            .where(RSSFeed.rsf_name == instruction.target)
            .with_for_update()
        )
        if feed is None:
            raise LookupError(f"RSS feed disappeared: {instruction.target}")

        now = utc_now()
        if instruction.action is ActionType.SET_RSS_INTERVAL:
            feed.rsf_poll_interval_seconds = instruction.parameters["seconds"]
            if feed.rsf_status == "active":
                feed.rsf_next_poll_at = now + timedelta(
                    seconds=feed.rsf_poll_interval_seconds
                )
                feed.rsf_next_poll_trigger = "schedule"
                feed.rsf_pending_instruction_id = instruction.instruction_id
        elif instruction.action is ActionType.RUN_RSS_NOW:
            feed.rsf_next_poll_at = now
            feed.rsf_next_poll_trigger = "run_now"
            feed.rsf_pending_instruction_id = instruction.instruction_id
        elif instruction.action is ActionType.PAUSE_RSS:
            feed.rsf_status = "paused"
            feed.rsf_next_poll_at = None
            feed.rsf_next_poll_trigger = "schedule"
            feed.rsf_pending_instruction_id = None
        elif instruction.action is ActionType.RESUME_RSS:
            feed.rsf_status = "active"
            feed.rsf_next_poll_at = now
            feed.rsf_next_poll_trigger = "schedule"
            feed.rsf_pending_instruction_id = instruction.instruction_id

        feed.rsf_updated_at = now
        await self.session.commit()

    async def claim_next_due(self, now: datetime | None = None) -> ClaimedFeed | None:
        """Claim one due feed and advance its visible schedule before execution."""

        claimed_at = now or utc_now()
        feed = await self.session.scalar(
            select(RSSFeed)
            .where(
                RSSFeed.rsf_next_poll_at.is_not(None),
                RSSFeed.rsf_next_poll_at <= claimed_at,
                or_(
                    RSSFeed.rsf_status == "active",
                    RSSFeed.rsf_next_poll_trigger == "run_now",
                ),
            )
            .order_by(RSSFeed.rsf_next_poll_at, RSSFeed.rsf_id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if feed is None:
            return None

        trigger = feed.rsf_next_poll_trigger
        instruction_id = feed.rsf_pending_instruction_id
        run = RSSFeedRun(
            rfr_rsf_id=feed.rsf_id,
            rfr_trigger=trigger,
            rfr_instruction_id=instruction_id,
            rfr_status="running",
            rfr_started_at=claimed_at,
        )
        self.session.add(run)

        if feed.rsf_status == "active":
            feed.rsf_next_poll_at = claimed_at + timedelta(
                seconds=feed.rsf_poll_interval_seconds
            )
        else:
            feed.rsf_next_poll_at = None
        feed.rsf_next_poll_trigger = "schedule"
        feed.rsf_pending_instruction_id = None
        feed.rsf_updated_at = claimed_at
        await self.session.commit()
        return ClaimedFeed(feed=feed, run=run)

    async def complete_run(
        self,
        *,
        run_id: int,
        feed_id: int,
        items_processed: int,
        completed_at: datetime | None = None,
    ) -> None:
        finished_at = completed_at or utc_now()
        run = await self.session.get(RSSFeedRun, run_id)
        feed = await self.session.get(RSSFeed, feed_id)
        if run is None or feed is None:
            raise LookupError("Claimed RSS execution state disappeared")
        run.rfr_status = "succeeded"
        run.rfr_completed_at = finished_at
        run.rfr_items_processed = items_processed
        feed.rsf_last_polled_at = finished_at
        feed.rsf_last_status = "succeeded"
        feed.rsf_last_items_processed = items_processed
        feed.rsf_last_error = None
        feed.rsf_updated_at = finished_at
        await self.session.commit()

    async def fail_run(
        self,
        *,
        run_id: int,
        feed_id: int,
        error: str,
        completed_at: datetime | None = None,
    ) -> None:
        """Record the failure only; retry/backoff policy is intentionally TBD."""

        finished_at = completed_at or utc_now()
        message = error[:2_000]
        run = await self.session.get(RSSFeedRun, run_id)
        feed = await self.session.get(RSSFeed, feed_id)
        if run is None or feed is None:
            raise LookupError("Claimed RSS execution state disappeared")
        run.rfr_status = "failed"
        run.rfr_completed_at = finished_at
        run.rfr_error = message
        feed.rsf_last_polled_at = finished_at
        feed.rsf_last_status = "failed"
        feed.rsf_last_items_processed = 0
        feed.rsf_last_error = message
        feed.rsf_updated_at = finished_at
        await self.session.commit()

    async def next_due_at(self) -> datetime | None:
        return await self.session.scalar(
            select(RSSFeed.rsf_next_poll_at)
            .where(
                RSSFeed.rsf_next_poll_at.is_not(None),
                or_(
                    RSSFeed.rsf_status == "active",
                    RSSFeed.rsf_next_poll_trigger == "run_now",
                ),
            )
            .order_by(RSSFeed.rsf_next_poll_at)
            .limit(1)
        )
