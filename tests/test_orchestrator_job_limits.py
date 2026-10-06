import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from sqlalchemy import create_engine, text

from orchestrator_agent.follow_up import FollowUpAnalysisExecutor, FollowUpAnalysisRepository
from orchestrator_agent.job_limits import JOB_TIMEOUT_ERROR, JOB_TIMEOUT_SECONDS
from orchestrator_agent.rss_executor import RSSFeedExecutor
from orchestrator_agent.rss_repository import RSSFeedRepository


class JobDeadlineTests(unittest.IsolatedAsyncioTestCase):
    async def check_executor(self, kind, cancel_service=False):
        cancelled = asyncio.Event()
        started = asyncio.Event()

        async def blocked(*args, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        repository = SimpleNamespace(session=SimpleNamespace(rollback=AsyncMock()))
        if kind == "follow_up":
            repository.fail_expired_jobs = AsyncMock()
            repository.claim_next = AsyncMock(side_effect=[
                SimpleNamespace(oaj_id=1), SimpleNamespace(oaj_id=2), None,
            ])
            repository.fail = AsyncMock()
            repository.succeed = AsyncMock()
            executor = FollowUpAnalysisExecutor(repository)
            async def execute(job):
                return await blocked() if job.oaj_id == 1 else 42
            executor._execute = execute
            run = executor.run_pending
            module = "orchestrator_agent.follow_up"
        else:
            repository.fail_expired_runs = AsyncMock()
            repository.claim_next_due = AsyncMock(side_effect=[
                SimpleNamespace(run=SimpleNamespace(rfr_id=i), feed=SimpleNamespace(
                    rsf_id=i, rsf_name=f"feed{i}", rsf_url="url", rsf_source_prefix="rss",
                )) for i in (1, 2)
            ] + [None])
            repository.fail_run = AsyncMock()
            repository.complete_run = AsyncMock()
            executor = RSSFeedExecutor(repository)
            run = executor.run_due
            module = "orchestrator_agent.rss_executor"

        async def ingest(*args, feed_name, **kwargs):
            return await blocked() if feed_name == "feed1" else [42]

        with patch(f"{module}.JOB_TIMEOUT_SECONDS", 0.01), patch(
            "orchestrator_agent.rss_executor.ingest_rss_feed", side_effect=ingest,
        ):
            if cancel_service:
                task = asyncio.create_task(run())
                await started.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            else:
                self.assertEqual(await run(), 2)

        self.assertTrue(cancelled.is_set())
        if cancel_service:
            repository.session.rollback.assert_not_awaited()
            (repository.fail if kind == "follow_up" else repository.fail_run).assert_not_awaited()
        else:
            repository.session.rollback.assert_awaited_once()
            if kind == "follow_up":
                repository.fail.assert_awaited_once_with(1, JOB_TIMEOUT_ERROR)
                repository.succeed.assert_awaited_once_with(2, 42)
                repository.fail_expired_jobs.assert_awaited_once()
            else:
                repository.fail_run.assert_awaited_once_with(
                    run_id=1, feed_id=1, error=JOB_TIMEOUT_ERROR,
                )
                repository.complete_run.assert_awaited_once_with(
                    run_id=2, feed_id=2, items_processed=1,
                )
                repository.fail_expired_runs.assert_awaited_once()

    async def test_follow_up_timeout_continues_queue(self):
        await self.check_executor("follow_up")

    async def test_rss_timeout_continues_queue(self):
        await self.check_executor("rss")

    async def test_follow_up_shutdown_propagates(self):
        await self.check_executor("follow_up", cancel_service=True)

    async def test_rss_shutdown_propagates(self):
        await self.check_executor("rss", cancel_service=True)

    def test_deadline_is_ten_minutes(self):
        self.assertEqual(JOB_TIMEOUT_SECONDS, 600)

    async def test_recovery_only_fails_overdue_running_records(self):
        now = datetime.now(timezone.utc)
        for repository_class, table, prefix, module in (
            (FollowUpAnalysisRepository, "orchestrator_analysis_jobs", "oaj", "follow_up"),
            (RSSFeedRepository, "rss_feed_runs", "rfr", "rss_repository"),
        ):
            with self.subTest(table=table):
                engine = create_engine("sqlite://")
                with engine.begin() as connection:
                    connection.execute(text(f"CREATE TABLE {table} ("
                        f"{prefix}_id INTEGER PRIMARY KEY, {prefix}_status TEXT, "
                        f"{prefix}_started_at DATETIME, {prefix}_completed_at DATETIME, "
                        f"{prefix}_error TEXT)"))
                    for record_id, status, age in (
                        (1, "running", timedelta(weeks=2)),
                        (2, "running", timedelta(minutes=9)),
                        (3, "succeeded", timedelta(weeks=2)),
                        (4, "pending", timedelta(weeks=2)),
                    ):
                        connection.execute(text(f"INSERT INTO {table} "
                            f"({prefix}_id, {prefix}_status, {prefix}_started_at) "
                            "VALUES (:id, :status, :started)"), {
                                "id": record_id, "status": status,
                                "started": (now - age).strftime("%Y-%m-%d %H:%M:%S.%f"),
                            })
                    session = SimpleNamespace(
                        execute=AsyncMock(side_effect=connection.execute), commit=AsyncMock(),
                    )
                    repository = repository_class(session)
                    with patch(f"orchestrator_agent.{module}.utc_now", return_value=now):
                        if prefix == "oaj":
                            await repository.fail_expired_jobs()
                        else:
                            await repository.fail_expired_runs()
                    rows = connection.execute(text(f"SELECT {prefix}_status, "
                        f"{prefix}_error, {prefix}_completed_at FROM {table} "
                        f"ORDER BY {prefix}_id")).all()
                    self.assertEqual([row[0] for row in rows],
                        ["failed", "running", "succeeded", "pending"])
                    self.assertEqual(rows[0][1], JOB_TIMEOUT_ERROR)
                    self.assertIsNotNone(rows[0][2])
                    self.assertTrue(all(row[1] is None for row in rows[1:]))
                    session.commit.assert_awaited_once()
                engine.dispose()
