import tempfile
import unittest
from pathlib import Path

from orchestrator_agent import ActionType, DecisionProposal, Orchestrator, WorkerReport
from orchestrator_agent.memory import JsonMemoryStore
from orchestrator_agent.policy import OrchestratorPolicy


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


if __name__ == "__main__":
    unittest.main()
