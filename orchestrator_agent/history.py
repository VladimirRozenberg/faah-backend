"""PostgreSQL audit history, separate from the compact runtime handoff memory."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models import Asset, OrchestratorAnalysisJob, OrchestratorCycle, OrchestratorDecision, Prompt, RSSFeed
from orchestrator_agent.schemas import BrainResult, CycleContext, MemoryState


def history_key(source: str, started_at: datetime) -> str:
    return f"{source}:{started_at.astimezone(timezone.utc).isoformat()}"


class OrchestratorHistoryRepository:
    def __init__(self, session: AsyncSession, source: str = "background"):
        self.session = session
        self.source = source

    async def begin(self, context: CycleContext, result: BrainResult) -> int:
        cycle = OrchestratorCycle(
            orc_history_key=history_key(self.source, context.started_at),
            orc_source=self.source,
            orc_started_at=context.started_at,
            orc_signal_window_start=context.signal_window_start,
            orc_prm_id=result.prompt_id,
            orc_model=result.model,
            orc_status="applying",
            orc_snapshot={
                "signal_ids": [item.signal_id for item in context.signals],
                "decision": result.decision.model_dump(mode="json"),
                "history_complete": True,
            },
            orc_raw_model_content=result.raw_content,
        )
        self.session.add(cycle)
        await self.session.flush()
        feeds = dict((await self.session.execute(select(RSSFeed.rsf_name, RSSFeed.rsf_id))).all())
        for position, proposal in enumerate(result.decision.rss_proposals):
            self.session.add(OrchestratorDecision(
                ord_cycle_id=cycle.orc_id,
                ord_position=position,
                ord_rsf_id=feeds.get(proposal.target),
                ord_proposal=proposal.model_dump(mode="json"),
                ord_status="pending",
            ))
        await self.session.commit()
        return cycle.orc_id

    async def record_decision(self, cycle_id: int, position: int, **values) -> None:
        await self.session.execute(
            update(OrchestratorDecision)
            .where(OrchestratorDecision.ord_cycle_id == cycle_id,
                   OrchestratorDecision.ord_position == position)
            .values(**values)
        )
        await self.session.commit()

    async def finish(self, cycle_id: int, error: str | None = None) -> None:
        await self.session.execute(
            update(OrchestratorCycle).where(OrchestratorCycle.orc_id == cycle_id)
            .values(orc_status="failed" if error else "completed",
                    orc_completed_at=datetime.now(timezone.utc), orc_error=error)
        )
        await self.session.commit()

    async def import_memory(self, state: MemoryState) -> None:
        """Import retained cycles once; do not invent missing legacy outcomes."""
        if not state.cycles:
            return
        existing = set((await self.session.scalars(
            select(OrchestratorCycle.orc_history_key)
            .where(OrchestratorCycle.orc_history_key.in_(
                [history_key(self.source, item.started_at) for item in state.cycles]
            ))
        )).all())
        missing = [item for item in state.cycles
                   if history_key(self.source, item.started_at) not in existing]
        if not missing:
            return
        prompt_ids = {item.prompt_id for item in missing if item.prompt_id is not None}
        valid_prompts = set((await self.session.scalars(
            select(Prompt.prm_id).where(Prompt.prm_id.in_(prompt_ids))
        )).all()) if prompt_ids else set()
        feeds = dict((await self.session.execute(select(RSSFeed.rsf_name, RSSFeed.rsf_id))).all())
        decisions = {item.instruction_id: item for item in state.decisions if item.instruction_id}
        for old in missing:
            cycle = OrchestratorCycle(
                orc_history_key=history_key(self.source, old.started_at),
                orc_source=self.source,
                orc_started_at=old.started_at,
                orc_signal_window_start=old.signal_window_start,
                orc_prm_id=old.prompt_id if old.prompt_id in valid_prompts else None,
                orc_status="legacy",
                orc_snapshot={**old.model_dump(mode="json"), "history_complete": False},
            )
            self.session.add(cycle)
            await self.session.flush()
            for position, instruction_id in enumerate(old.approved_instruction_ids):
                record = decisions.get(instruction_id)
                if record is None:
                    continue
                self.session.add(OrchestratorDecision(
                    ord_cycle_id=cycle.orc_id,
                    ord_position=position,
                    ord_rsf_id=feeds.get(record.proposal.target),
                    ord_proposal=record.proposal.model_dump(mode="json"),
                    ord_approved=True,
                    ord_status="legacy_approved",
                    ord_instruction_id=instruction_id,
                ))
            if old.created_follow_up_job_ids:
                await self.session.execute(
                    update(OrchestratorAnalysisJob)
                    .where(OrchestratorAnalysisJob.oaj_id.in_(old.created_follow_up_job_ids),
                           OrchestratorAnalysisJob.oaj_cycle_id.is_(None))
                    .values(oaj_cycle_id=cycle.orc_id)
                )
        await self.session.commit()

    async def list_page(self, page: int, page_size: int) -> dict:
        total = await self.session.scalar(select(func.count()).select_from(OrchestratorCycle))
        cycles = list((await self.session.scalars(
            select(OrchestratorCycle)
            .order_by(OrchestratorCycle.orc_started_at.desc(), OrchestratorCycle.orc_id.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )).all())
        ids = [cycle.orc_id for cycle in cycles]
        decisions = list((await self.session.scalars(
            select(OrchestratorDecision).where(OrchestratorDecision.ord_cycle_id.in_(ids))
            .order_by(OrchestratorDecision.ord_position)
        )).all()) if ids else []
        jobs = list((await self.session.scalars(
            select(OrchestratorAnalysisJob).where(OrchestratorAnalysisJob.oaj_cycle_id.in_(ids))
            .order_by(OrchestratorAnalysisJob.oaj_id)
        )).all()) if ids else []
        grouped_decisions = {cycle_id: [] for cycle_id in ids}
        grouped_jobs = {cycle_id: [] for cycle_id in ids}
        asset_ids = {job.oaj_ast_id for job in jobs}
        assets = dict((await self.session.execute(
            select(Asset.ast_id, Asset.ast_symbol).where(Asset.ast_id.in_(asset_ids))
        )).all()) if asset_ids else {}
        for item in decisions:
            grouped_decisions[item.ord_cycle_id].append({
                "decision_id": item.ord_id, "feed_id": item.ord_rsf_id,
                "proposal": item.ord_proposal, "approved": item.ord_approved,
                "status": item.ord_status, "rejection_reason": item.ord_rejection_reason,
                "error": item.ord_error, "instruction_id": item.ord_instruction_id,
            })
        for job in jobs:
            grouped_jobs[job.oaj_cycle_id].append({
                "job_id": job.oaj_id, "asset_id": job.oaj_ast_id,
                "asset_symbol": assets[job.oaj_ast_id],
                "question": job.oaj_question, "reason": job.oaj_reason,
                "priority": job.oaj_priority, "status": job.oaj_status,
                "result_analysis_id": job.oaj_result_anl_id, "error": job.oaj_error,
                "requested_at": job.oaj_requested_at, "started_at": job.oaj_started_at,
                "completed_at": job.oaj_completed_at,
            })
        items = []
        for cycle in cycles:
            snapshot = cycle.orc_snapshot
            decision = snapshot.get("decision", snapshot)
            started_at = cycle.orc_started_at.replace(
                tzinfo=cycle.orc_started_at.tzinfo or timezone.utc
            )
            items.append({
                "cycle_id": cycle.orc_id, "source": cycle.orc_source,
                "started_at": started_at, "completed_at": cycle.orc_completed_at,
                "signal_window_start": cycle.orc_signal_window_start,
                "prompt_id": cycle.orc_prm_id, "model": cycle.orc_model,
                "status": cycle.orc_status, "error": cycle.orc_error,
                "history_complete": snapshot["history_complete"],
                "signal_ids": snapshot["signal_ids"],
                "situation_summary": decision["situation_summary"],
                "follow_up_analysis": decision["follow_up_analysis"],
                "next_instructions": decision["next_instructions"],
                "next_run_in_seconds": decision["next_run_in_seconds"],
                "next_run_at": started_at + timedelta(seconds=decision["next_run_in_seconds"]),
                "rejected_rss_proposals": snapshot.get("rejected_rss_proposals", sum(
                    item["status"] == "rejected" for item in grouped_decisions[cycle.orc_id]
                )),
                "rss_decisions": grouped_decisions[cycle.orc_id],
                "follow_up_jobs": grouped_jobs[cycle.orc_id],
            })
        return {"count": total, "page": page, "page_size": page_size, "items": items}
