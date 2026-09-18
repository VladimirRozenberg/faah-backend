import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from orchestrator_agent import (
    ActionType,
    DecisionProposal,
    Orchestrator,
    OrchestrationLoop,
    WorkerReport,
)
from orchestrator_agent.context import StaticContextProvider
from orchestrator_agent.follow_up import resolve_asset_symbol
from orchestrator_agent.memory import JsonMemoryStore
from orchestrator_agent.policy import OrchestratorPolicy
from orchestrator_agent.schemas import (
    AnalysisFollowUp,
    AnalysisFollowUpJobState,
    AnalysisSummary,
    BrainResult,
    CycleDecision,
    SignalSnapshot,
)
from models import Asset


class RecordingFollowUpRepository:
    def __init__(self, now):
        self.now = now
        self.requests = []
        self.states = []

    async def list_states(self, **_kwargs):
        return list(self.states)

    async def enqueue_many(self, requests):
        self.requests.extend(requests)
        created = [
            AnalysisFollowUpJobState(
                job_id=index + 1,
                asset_id=3,
                asset_symbol=request.asset_symbol,
                question=request.question,
                reason=request.reason,
                priority=request.priority,
                status="pending",
                requested_at=self.now,
            )
            for index, request in enumerate(requests)
        ]
        self.states.extend(created)
        return created


class RecordingBrain:
    def __init__(self):
        self.contexts = []

    async def decide(self, context):
        self.contexts.append(context)
        decision = CycleDecision(
            situation_summary="The new buy conflicts with an older risk warning.",
            follow_up_analysis=[
                AnalysisFollowUp(
                    asset_symbol="ACME",
                    question="Has the regulatory risk been resolved?",
                    reason="The newest summary does not address it.",
                    priority=5,
                )
            ],
            rss_proposals=[
                DecisionProposal(
                    action=ActionType.SET_RSS_INTERVAL,
                    target="Investing.com",
                    parameters={"seconds": 300},
                    reason="Track a time-sensitive unresolved catalyst.",
                    confidence=0.81,
                ),
                DecisionProposal(
                    action=ActionType.RUN_RSS_NOW,
                    target="Forbidden feed",
                    reason="This must be rejected by policy.",
                    confidence=0.99,
                ),
            ],
            next_instructions="Check the regulatory follow-up before trusting ACME.",
            next_run_in_seconds=600,
        )
        return BrainResult(
            decision=decision,
            model="test-model",
            raw_content=decision.model_dump_json(),
            provider_response={"id": "test-completion", "choices": []},
        )


class OrchestratorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.memory = JsonMemoryStore(Path(self.temp_dir.name) / "memory.json")
        self.agent = Orchestrator(
            OrchestratorPolicy(allowed_feeds=frozenset({"Investing.com"})),
            memory=self.memory,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    async def test_approved_instruction_is_queued_and_remembered(self):
        instruction = await self.agent.submit(
            DecisionProposal(
                action=ActionType.SET_RSS_INTERVAL,
                target="Investing.com",
                parameters={"seconds": 300},
                reason="News volume increased",
                confidence=0.80,
            )
        )

        self.assertIsNotNone(instruction)
        queued = await self.agent.bus.queue_for("Investing.com").get()
        self.assertEqual(queued.parameters["seconds"], 300)
        self.assertTrue(self.memory.load().decisions[-1].approved)

    async def test_policy_rejects_excessive_polling(self):
        instruction = await self.agent.submit(
            DecisionProposal(
                action=ActionType.SET_RSS_INTERVAL,
                target="Investing.com",
                parameters={"seconds": 5},
                reason="Poll very quickly",
                confidence=0.99,
            )
        )

        self.assertIsNone(instruction)
        self.assertFalse(self.memory.load().decisions[-1].approved)

    async def test_policy_rejects_interval_above_two_hours(self):
        instruction = await self.agent.submit(
            DecisionProposal(
                action=ActionType.SET_RSS_INTERVAL,
                target="Investing.com",
                parameters={"seconds": 7_201},
                reason="Poll an inactive feed too slowly",
                confidence=0.99,
            )
        )

        self.assertIsNone(instruction)
        rejection = self.memory.load().decisions[-1]
        self.assertFalse(rejection.approved)
        self.assertIn("7200", rejection.rejection_reason)

    def test_follow_up_asset_aliases_resolve_only_unique_symbols(self):
        assets = [
            Asset(ast_id=1, ast_symbol="USDJPY=X", ast_name="USD/JPY", ast_type="forex"),
            Asset(ast_id=2, ast_symbol="GC=F", ast_name="Gold", ast_type="future"),
            Asset(ast_id=3, ast_symbol="BRK-B", ast_name="Berkshire", ast_type="stock"),
        ]

        self.assertEqual(resolve_asset_symbol("USDJPY", assets).ast_id, 1)
        self.assertEqual(resolve_asset_symbol("gc", assets).ast_id, 2)
        self.assertEqual(resolve_asset_symbol("BRKB", assets).ast_id, 3)
        self.assertIsNone(resolve_asset_symbol("UNKNOWN", assets))

        ambiguous = assets + [
            Asset(ast_id=4, ast_symbol="GC", ast_name="Example", ast_type="stock")
        ]
        self.assertIsNone(resolve_asset_symbol("G.C", ambiguous))

    def test_worker_reports_update_performance_memory(self):
        self.agent.report(
            WorkerReport(
                worker="Investing.com",
                success=True,
                duration_ms=120,
                items_processed=4,
            )
        )

        metrics = self.memory.load().worker_metrics["Investing.com"]
        self.assertEqual(metrics.runs, 1)
        self.assertEqual(metrics.successes, 1)
        self.assertEqual(metrics.items_processed, 4)

    async def test_cycle_reads_window_history_and_persists_handoff(self):
        now = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)
        signal = SignalSnapshot(
            signal_id=9,
            analysis_id=20,
            asset_id=3,
            asset_symbol="ACME",
            action="buy",
            confidence=82,
            created_at=now - timedelta(minutes=30),
        )
        old_signal = signal.model_copy(
            update={"signal_id": 8, "created_at": now - timedelta(hours=2)}
        )
        history = AnalysisSummary(
            analysis_id=12,
            asset_id=3,
            asset_symbol="ACME",
            summary="Regulatory risk remains unresolved.",
            created_at=now - timedelta(days=2),
        )
        brain = RecordingBrain()
        follow_ups = RecordingFollowUpRepository(now)
        loop = OrchestrationLoop(
            self.agent,
            StaticContextProvider([old_signal, signal], [history]),
            brain,
            follow_up_repository=follow_ups,
        )

        result = await loop.run_once(now)

        self.assertEqual([item.signal_id for item in result.context.signals], [9])
        self.assertEqual(result.context.analysis_history, [history])
        self.assertIn("First run", result.context.previous_instructions)
        self.assertEqual(len(result.approved_instructions), 1)
        self.assertEqual(result.rejected_rss_proposals, 1)
        self.assertEqual(result.model, "test-model")
        self.assertEqual(len(result.created_follow_up_jobs), 1)
        self.assertEqual(result.created_follow_up_jobs[0].asset_symbol, "ACME")
        self.assertEqual(follow_ups.requests, result.decision.follow_up_analysis)
        self.assertEqual(
            result.complete_model_response["id"],
            "test-completion",
        )
        state = self.memory.load()
        self.assertEqual(state.last_cycle_at, now)
        self.assertEqual(state.next_instructions, result.decision.next_instructions)
        self.assertEqual(state.cycles[-1].signal_ids, [9])
        self.assertEqual(state.cycles[-1].created_follow_up_job_ids, [1])
        self.assertEqual(state.cycles[-1].next_run_in_seconds, 600)

        await loop.run_once(now + timedelta(hours=1))

        self.assertEqual(
            brain.contexts[-1].signal_window_start,
            now - timedelta(minutes=5),
        )
        self.assertEqual(
            brain.contexts[-1].previous_instructions,
            "Check the regulatory follow-up before trusting ACME.",
        )


if __name__ == "__main__":
    unittest.main()
