"""Tests sans accès à PostgreSQL ni à Twelve Data."""
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.dialects import postgresql
from assets import backfill_logos as worker


class BackfillTests(unittest.IsolatedAsyncioTestCase):
    async def step(self, values, fill=None):
        db = MagicMock()
        db.scalar = AsyncMock(side_effect=values)
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=db)
        session.__aexit__ = AsyncMock(return_value=False)
        with patch.object(worker, "AsyncSessionLocal", return_value=session), patch.object(
            worker, "fill_missing_logo", AsyncMock(side_effect=fill)
        ) as download:
            result = await worker.fill_one()
        return result, db, download

    async def test_busy_automatic_worker_skips_download(self):
        result, db, download = await self.step([False])
        self.assertEqual(result, ("wait", None))
        self.assertEqual(db.scalar.await_count, 1)
        download.assert_not_awaited()

    async def test_no_eligible_asset_stops(self):
        result, db, download = await self.step([True, None])
        self.assertEqual(result, ("done", None))
        download.assert_not_awaited()
        # Vérifier la requête réellement construite et son dialecte PostgreSQL.
        sql = str(db.scalar.call_args.args[0].compile(dialect=postgresql.dialect()))
        self.assertIn("ast_logo_mime_type IS NULL", sql)
        self.assertIn("ast_logo_last_attempt_at IS NULL", sql)
        self.assertIn("NULLS FIRST", sql)
        self.assertIn("LIMIT", sql)

    async def test_success_failure_and_quota_are_distinguished(self):
        for outcome in ("saved", "missing", "wait"):
            asset = SimpleNamespace(ast_symbol="AVEX", ast_logo_mime_type=None, ast_logo_last_attempt_at=None)
            async def fill(db, item):
                if outcome != "wait":
                    item.ast_logo_last_attempt_at = datetime.now(timezone.utc)
                if outcome == "saved":
                    item.ast_logo_mime_type = "image/png"
            result, db, download = await self.step([True, asset], fill)
            self.assertEqual(result, (outcome, "AVEX" if outcome != "wait" else None))
            download.assert_awaited_once_with(db, asset)
            db.begin.assert_called_once()

    async def test_no_key_starts_no_database_work(self):
        with patch.dict("os.environ", {"TWELVE_DATA_API_KEY": ""}), patch.object(worker, "fill_one", AsyncMock()) as step:
            with self.assertRaises(SystemExit):
                await worker.run(3)
            step.assert_not_awaited()
