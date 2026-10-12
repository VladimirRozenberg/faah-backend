import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from orchestrator_agent.context_limits import MAX_CONTEXT_BYTES, bounded_context
from orchestrator_agent.schemas import (
    AnalysisFollowUpJobState, AnalysisSummary, CycleContext, SignalSnapshot,
)


class ContextLimitsTests(unittest.TestCase):
    def context(self):
        now = datetime(2026, 10, 10, tzinfo=timezone.utc)
        return CycleContext(started_at=now, signal_window_start=now - timedelta(hours=1),
                            previous_instructions="Check unresolved evidence.")

    def test_large_unicode_context_fits_budget_without_mutating_original(self):
        context = self.context()
        now = context.started_at
        context.signals = [SignalSnapshot(
            signal_id=i, analysis_id=i, asset_id=i, asset_symbol=f"A{i}",
            action="buy", created_at=now - timedelta(seconds=i),
            generating_analysis_summary="市場" * 5000,
        ) for i in range(400)]
        context.analysis_history = [AnalysisSummary(
            analysis_id=i, asset_id=i, asset_symbol=f"A{i}",
            summary="市場" * 5000, created_at=now,
        ) for i in range(400)]
        result = bounded_context(context)
        self.assertLessEqual(len(result.model_dump_json().encode("utf-8")), MAX_CONTEXT_BYTES)
        self.assertEqual(result.signals[0].signal_id, 0)
        self.assertGreater(result.context_limits["signals_omitted"], 0)
        self.assertEqual(len(context.signals), 400)
        self.assertEqual(len(context.signals[0].generating_analysis_summary), 10000)

    def test_shared_analysis_is_deduplicated_with_asset_links_and_is_idempotent(self):
        context = self.context()
        context.analysis_history = [AnalysisSummary(
            analysis_id=42, asset_id=i, asset_symbol=f"A{i}",
            summary="Evidence " * 500, created_at=context.started_at,
        ) for i in (1, 2, 3)]
        result = bounded_context(context)
        self.assertEqual(len(result.analysis_history), 1)
        self.assertEqual(result.analysis_asset_ids[42], [1, 2, 3])
        self.assertEqual(result.context_limits["analysis_history_omitted"], 2)
        self.assertEqual(bounded_context(result), result)

    def test_active_jobs_take_priority_and_full_reports_are_omitted(self):
        context = self.context()
        context.follow_up_jobs = [AnalysisFollowUpJobState(
            job_id=i, asset_id=1, asset_symbol="A", question="Unresolved risk?",
            reason="Conflicting evidence", priority=5,
            status="pending" if i == 0 else "succeeded",
            requested_at=context.started_at - timedelta(days=1) if i == 0 else context.started_at,
            result_summary="Summary", result_text="Full report" * 10000,
        ) for i in range(40)]
        result = bounded_context(context)
        self.assertEqual(result.follow_up_jobs[0].job_id, 0)
        self.assertTrue(all(job.result_text is None for job in result.follow_up_jobs))
        self.assertEqual(result.context_limits["follow_up_jobs_omitted"], 10)


class PromptGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_oversized_required_fields_fail_before_recording_or_provider_call(self):
        from orchestrator_agent.brain import LLMOrchestrationBrain
        now = datetime(2026, 10, 10, tzinfo=timezone.utc)
        context = CycleContext(
            started_at=now, signal_window_start=now, previous_instructions="Check",
            allowed_rss_feeds=["X" * 200_000],
        )
        with patch("prompt.recording.record_prompt", new_callable=AsyncMock) as record, \
                patch("prompt.llm_client.get_alibaba_client") as client:
            with self.assertRaisesRegex(ValueError, "context budget"):
                await LLMOrchestrationBrain(AsyncMock()).decide(context)
            record.assert_not_awaited()
            client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
