"""One-shot, restartable orchestration loop."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol

from orchestrator_agent.brain import OrchestrationBrain
from orchestrator_agent.context import ContextProvider
from orchestrator_agent.orchestrator import Orchestrator
from orchestrator_agent.schemas import (
    AnalysisFollowUp,
    AnalysisFollowUpJobState,
    CycleContext,
    CycleRecord,
    CycleResult,
    RSSFeedState,
)


DEFAULT_FIRST_RUN_INSTRUCTIONS = """First run: inspect the last hour of signals.
Compare each signal with its full supplied analysis history. Prioritize unresolved,
time-sensitive contradictions and avoid changing RSS cadence without a concrete
reason. Leave a short, actionable handoff for the next scheduled run."""


class FeedStateProvider(Protocol):
    async def feed_states(self) -> list[RSSFeedState]: ...


class FollowUpRepository(Protocol):
    async def list_states(
        self,
        *,
        since: datetime | None = None,
        asset_ids: set[int] | None = None,
        limit: int = 100,
    ) -> list[AnalysisFollowUpJobState]: ...

    async def enqueue_many(
        self,
        requests: list[AnalysisFollowUp],
    ) -> list[AnalysisFollowUpJobState]: ...


class OrchestrationLoop:
    def __init__(
        self,
        orchestrator: Orchestrator,
        provider: ContextProvider,
        brain: OrchestrationBrain,
        *,
        feed_state_provider: FeedStateProvider | None = None,
        follow_up_repository: FollowUpRepository | None = None,
        first_window: timedelta = timedelta(hours=1),
        signal_window_overlap: timedelta = timedelta(minutes=5),
    ) -> None:
        self.orchestrator = orchestrator
        self.provider = provider
        self.brain = brain
        self.feed_state_provider = feed_state_provider
        self.follow_up_repository = follow_up_repository
        self.first_window = first_window
        self.signal_window_overlap = signal_window_overlap

    async def run_once(self, now: datetime | None = None) -> CycleResult:
        started_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        state = self.orchestrator.memory.load()
        window_start = (
            state.last_cycle_at - self.signal_window_overlap
            if state.last_cycle_at is not None
            else started_at - self.first_window
        )
        previous = state.next_instructions or DEFAULT_FIRST_RUN_INSTRUCTIONS

        signals = await self.provider.recent_signals(window_start, started_at)
        asset_ids = {signal.asset_id for signal in signals}
        history = await self.provider.analysis_history(asset_ids, started_at)
        feed_states = (
            await self.feed_state_provider.feed_states()
            if self.feed_state_provider is not None
            else []
        )
        follow_up_jobs = (
            await self.follow_up_repository.list_states(
                since=window_start,
                asset_ids=asset_ids,
            )
            if self.follow_up_repository is not None
            else []
        )
        context = CycleContext(
            started_at=started_at,
            signal_window_start=window_start,
            previous_instructions=previous,
            signals=signals,
            analysis_history=history,
            follow_up_jobs=follow_up_jobs,
            allowed_rss_feeds=sorted(self.orchestrator.policy.allowed_feeds),
            rss_feed_states=feed_states,
        )
        brain_result = await self.brain.decide(context)
        decision = brain_result.decision

        created_follow_up_jobs = (
            await self.follow_up_repository.enqueue_many(
                decision.follow_up_analysis
            )
            if self.follow_up_repository is not None
            else []
        )

        approved = []
        rejected = 0
        for proposal in decision.rss_proposals:
            instruction = await self.orchestrator.submit(proposal)
            if instruction is None:
                rejected += 1
            else:
                approved.append(instruction)

        self.orchestrator.memory.record_cycle(
            CycleRecord(
                started_at=started_at,
                signal_window_start=window_start,
                signal_ids=[signal.signal_id for signal in signals],
                situation_summary=decision.situation_summary,
                follow_up_analysis=decision.follow_up_analysis,
                created_follow_up_job_ids=[
                    item.job_id for item in created_follow_up_jobs
                ],
                approved_instruction_ids=[item.instruction_id for item in approved],
                rejected_rss_proposals=rejected,
                next_instructions=decision.next_instructions,
                next_run_in_seconds=decision.next_run_in_seconds,
            )
        )
        return CycleResult(
            context=context,
            decision=decision,
            model=brain_result.model,
            raw_model_content=brain_result.raw_content,
            complete_model_response=brain_result.provider_response,
            created_follow_up_jobs=created_follow_up_jobs,
            approved_instructions=approved,
            rejected_rss_proposals=rejected,
        )
