import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from db import Base, get_db
from models import Asset, OrchestratorAnalysisJob, OrchestratorCycle, OrchestratorDecision, Prompt, RSSFeed
from orchestrator_agent.context import StaticContextProvider
from orchestrator_agent.follow_up import FollowUpAnalysisRepository
from orchestrator_agent.history import OrchestratorHistoryRepository
from orchestrator_agent.loop import OrchestrationLoop
from orchestrator_agent.memory import JsonMemoryStore
from orchestrator_agent.orchestrator import Orchestrator
from orchestrator_agent.policy import OrchestratorPolicy
from orchestrator_agent.rss_repository import RSSFeedRepository
from orchestrator_agent.schemas import (
    ActionType, AnalysisFollowUp, BrainResult, CycleContext, CycleDecision, CycleRecord,
    DecisionProposal, DecisionRecord, MemoryState, OrchestratorDecisionPage,
)
from routers.orchestrator import router


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(type_, compiler, **kwargs):
    return "JSON"


class OrchestratorHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.execute(text("PRAGMA foreign_keys=ON"))
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.directory = tempfile.TemporaryDirectory()
        self.memory = JsonMemoryStore(Path(self.directory.name) / "memory.json")
        self.now = datetime(2026, 10, 6, 10, tzinfo=timezone.utc)
        async with self.sessions() as db:
            db.add(RSSFeed(rsf_name="Markets", rsf_url="https://example.com/rss", rsf_source_prefix="rss"))
            db.add(Asset(ast_symbol="AAA", ast_name="Asset A", ast_type="stock"))
            await db.commit()

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.directory.cleanup()

    def proposal(self, target="Markets", confidence=0.8):
        return DecisionProposal(action=ActionType.SET_RSS_INTERVAL, target=target,
                                parameters={"seconds": 600}, reason="Urgent research", confidence=confidence)

    def result(self, proposals=None, follow_ups=None, prompt_id=None):
        return BrainResult(
            decision=CycleDecision(situation_summary="Unresolved market news",
                rss_proposals=proposals or [], follow_up_analysis=follow_ups or [],
                next_instructions="Recheck the evidence", next_run_in_seconds=600),
            model="test-model", raw_content="model JSON", provider_response={}, prompt_id=prompt_id,
        )

    def context(self, when=None):
        started = when or self.now
        return CycleContext(started_at=started, signal_window_start=started - timedelta(hours=1),
                            previous_instructions="Check new news")

    async def run_cycle(self, db, result, bus=None):
        history = OrchestratorHistoryRepository(db)
        orchestrator = Orchestrator(policy=OrchestratorPolicy(allowed_feeds=frozenset({"Markets"})),
            memory=self.memory, bus=bus or RSSFeedRepository(db), history=history)
        return await OrchestrationLoop(orchestrator, StaticContextProvider(signals=[], analyses=[]),
            AsyncMock(decide=AsyncMock(return_value=result)),
            follow_up_repository=FollowUpAnalysisRepository(db)).run_once(self.now)

    async def test_cycle_captures_policy_results_and_links_jobs(self):
        async with self.sessions() as db:
            prompt = Prompt(prm_name="cycle", prm_type="orchestration", prm_prompt_text="context")
            db.add(prompt)
            await db.commit()
            result = self.result(
                [self.proposal(), self.proposal(confidence=0.2), self.proposal(target="Unknown")],
                [AnalysisFollowUp(asset_symbol="AAA", question="What changed?", reason="New evidence", priority=4)],
                prompt.prm_id,
            )
            await self.run_cycle(db, result)
            page = OrchestratorDecisionPage.model_validate(await OrchestratorHistoryRepository(db).list_page(1, 20))
            cycle = page.items[0]
            self.assertEqual(page.count, 1)
            self.assertEqual(cycle.status, "completed")
            self.assertEqual(cycle.prompt_id, prompt.prm_id)
            self.assertEqual([item.status for item in cycle.rss_decisions], ["applied", "rejected", "rejected"])
            self.assertEqual(cycle.rejected_rss_proposals, 2)
            self.assertIsNone(cycle.rss_decisions[2].feed_id)
            self.assertIn("Confidence", cycle.rss_decisions[1].rejection_reason)
            self.assertEqual(cycle.follow_up_jobs[0].asset_symbol, "AAA")
            self.assertEqual(cycle.follow_up_analysis[0].question, "What changed?")
            job = await db.get(OrchestratorAnalysisJob, cycle.follow_up_jobs[0].job_id)
            self.assertEqual(job.oaj_cycle_id, cycle.cycle_id)
            feed = await db.scalar(select(RSSFeed))
            self.assertEqual(feed.rsf_poll_interval_seconds, 600)
            self.assertEqual(cycle.next_run_at, self.now + timedelta(seconds=600))

    async def test_application_failure_is_distinct_from_approval(self):
        async with self.sessions() as db:
            bus = AsyncMock()
            bus.publish.side_effect = RuntimeError("Schedule update failed")
            with self.assertRaisesRegex(RuntimeError, "Schedule update failed"):
                await self.run_cycle(db, self.result([self.proposal()]), bus)
            cycle = (await OrchestratorHistoryRepository(db).list_page(1, 20))["items"][0]
            self.assertEqual(cycle["status"], "failed")
            self.assertEqual(cycle["error"], "Schedule update failed")
            self.assertTrue(cycle["rss_decisions"][0]["approved"])
            self.assertEqual(cycle["rss_decisions"][0]["status"], "failed")

    async def test_history_survives_memory_reset_and_does_not_duplicate_cycles(self):
        async with self.sessions() as db:
            await self.run_cycle(db, self.result())
            repository = OrchestratorHistoryRepository(db)
            await repository.import_memory(self.memory.load())
            self.assertEqual((await repository.list_page(1, 20))["count"], 1)
            self.memory.path.unlink()
            self.assertEqual((await repository.list_page(1, 20))["count"], 1)

    async def test_legacy_import_is_idempotent_and_marks_missing_details(self):
        async with self.sessions() as db:
            job = OrchestratorAnalysisJob(oaj_ast_id=1, oaj_question="Question", oaj_reason="Reason",
                                         oaj_priority=3, oaj_status="pending")
            db.add(job)
            await db.commit()
            old = CycleRecord(started_at=self.now, signal_window_start=self.now - timedelta(hours=1),
                prompt_id=999, signal_ids=[123], situation_summary="Old summary", next_instructions="Old handoff",
                approved_instruction_ids=["legacy-instruction"], rejected_rss_proposals=2,
                created_follow_up_job_ids=[job.oaj_id])
            state = MemoryState(cycles=[old], decisions=[DecisionRecord(proposal=self.proposal(),
                approved=True, instruction_id="legacy-instruction")])
            repository = OrchestratorHistoryRepository(db)
            await repository.import_memory(state)
            await repository.import_memory(state)
            page = OrchestratorDecisionPage.model_validate(await repository.list_page(1, 20))
            job_id = job.oaj_id
            self.assertEqual(page.count, 1)
            cycle = page.items[0]
            self.assertFalse(cycle.history_complete)
            self.assertIsNone(cycle.prompt_id)
            self.assertEqual(cycle.status, "legacy")
            self.assertEqual(cycle.rejected_rss_proposals, 2)
            self.assertEqual(cycle.rss_decisions[0].status, "legacy_approved")
            self.assertEqual(len(cycle.follow_up_jobs), 1)
            db.expire_all()
            self.assertEqual((await db.get(OrchestratorAnalysisJob, job_id)).oaj_cycle_id, cycle.cycle_id)

    async def test_endpoint_pagination_order_count_empty_page_and_validation(self):
        async with self.sessions() as db:
            repository = OrchestratorHistoryRepository(db)
            for minutes in (0, 1, 2):
                cycle_id = await repository.begin(self.context(self.now + timedelta(minutes=minutes)), self.result())
                await repository.finish(cycle_id)
            expected = list((await db.scalars(select(OrchestratorCycle.orc_id)
                .order_by(OrchestratorCycle.orc_started_at.desc()))).all())
        app = FastAPI()
        app.include_router(router)
        async def override_db():
            async with self.sessions() as db:
                yield db
        app.dependency_overrides[get_db] = override_db
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            first = await client.get("/api/orchestrator/decisions?page=1&page_size=2")
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.json()["count"], 3)
            self.assertEqual([item["cycle_id"] for item in first.json()["items"]], expected[:2])
            second = (await client.get("/api/orchestrator/decisions?page=2&page_size=2")).json()
            self.assertEqual([item["cycle_id"] for item in second["items"]], expected[2:])
            empty = (await client.get("/api/orchestrator/decisions?page=3&page_size=2")).json()
            self.assertEqual(empty["items"], [])
            self.assertEqual(empty["count"], 3)
            for query in ("page=0", "page_size=0", "page_size=101"):
                self.assertEqual((await client.get(f"/api/orchestrator/decisions?{query}")).status_code, 422)

    async def test_foreign_keys_and_delete_rules_preserve_audit(self):
        async with self.sessions() as db:
            prompt = Prompt(prm_name="cycle", prm_type="orchestration", prm_prompt_text="context")
            db.add(prompt)
            await db.commit()
            repository = OrchestratorHistoryRepository(db)
            cycle_id = await repository.begin(self.context(), self.result([self.proposal()], prompt_id=prompt.prm_id))
            job = OrchestratorAnalysisJob(oaj_ast_id=1, oaj_cycle_id=cycle_id,
                oaj_question="Question", oaj_reason="Reason", oaj_priority=3, oaj_status="pending")
            db.add(job)
            await db.commit()
            job_id = job.oaj_id
            feed = await db.scalar(select(RSSFeed))
            await db.delete(feed)
            await db.delete(prompt)
            await db.commit()
            db.expire_all()
            decision = await db.scalar(select(OrchestratorDecision))
            self.assertIsNone(decision.ord_rsf_id)
            self.assertEqual(decision.ord_proposal["target"], "Markets")
            cycle = await db.get(OrchestratorCycle, cycle_id)
            self.assertIsNone(cycle.orc_prm_id)
            await db.delete(cycle)
            await db.commit()
            db.expire_all()
            self.assertIsNone((await db.get(OrchestratorAnalysisJob, job_id)).oaj_cycle_id)
            self.assertEqual(await db.scalar(select(func.count()).select_from(OrchestratorDecision)), 0)

    async def test_swagger_reset_imports_old_history_before_deleting_memory(self):
        old = CycleRecord(started_at=self.now - timedelta(days=1),
            signal_window_start=self.now - timedelta(days=1, hours=1),
            situation_summary="Before reset", next_instructions="Old handoff")
        self.memory.record_cycle(old)
        app = FastAPI()
        app.include_router(router)
        async def override_db():
            async with self.sessions() as db:
                yield db
        app.dependency_overrides[get_db] = override_db
        brain = AsyncMock()
        brain.decide.return_value = self.result()
        with patch.dict("os.environ", {"ORCHESTRATOR_TEST_MEMORY_PATH": str(self.memory.path)}), patch(
            "routers.orchestrator.LLMOrchestrationBrain", return_value=brain,
        ):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/api/orchestrator/test-run?reset_memory=true")
                self.assertEqual(response.status_code, 200)
                self.assertIsNotNone(response.json()["cycle_id"])
                history = (await client.get("/api/orchestrator/decisions")).json()
                self.assertEqual(history["count"], 2)
                self.assertTrue(all(cycle["source"] == "test" for cycle in history["items"]))
                self.assertEqual(history["items"][1]["situation_summary"], "Before reset")
