import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pandas as pd

from assets.market_data import get_latest_daily_quotes
from live_market.market_schemas import LiveQuote
from live_market.worker import (
    WorkerRuntime,
    get_asset_symbols,
    process_message,
    count_price_availability,
    refresh_stale_historical_quotes,
)


class LiveMarketWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_asset_symbols_includes_untracked_assets(self):
        database = SimpleNamespace(
            scalars=AsyncMock(
                return_value=SimpleNamespace(all=lambda: ["AAPL", "MSFT"])
            )
        )

        class SessionContext:
            async def __aenter__(self):
                return database

            async def __aexit__(self, *args):
                return None

        with patch(
            "live_market.worker.AsyncSessionLocal",
            return_value=SessionContext(),
        ):
            symbols = await get_asset_symbols()

        query = database.scalars.await_args.args[0]
        self.assertIsNone(query.whereclause)
        self.assertEqual(symbols, ["AAPL", "MSFT"])

    async def test_quote_updates_worker_runtime_after_redis_write(self):
        runtime = WorkerRuntime()
        with patch(
            "live_market.worker.save_latest_quote",
            new=AsyncMock(),
        ) as save_quote:
            await process_message(
                {
                    "id": "aapl",
                    "price": "230.5",
                    "time": "1790928000",
                    "day_volume": "100",
                    "previous_close": 229.0,
                    "change": 1.5,
                    "change_percent": 0.65,
                },
                runtime,
            )

        saved_quote = save_quote.await_args.args[0]
        self.assertEqual(saved_quote.previous_close, 229.0)
        self.assertEqual(saved_quote.change, 1.5)
        self.assertEqual(saved_quote.change_percent, 0.65)
        self.assertEqual(runtime.quotes_received, 1)
        self.assertIsNotNone(runtime.last_quote_at)
        self.assertIsNone(runtime.error)

    async def test_redis_write_failure_does_not_break_quote_listener(self):
        runtime = WorkerRuntime()
        with patch(
            "live_market.worker.save_latest_quote",
            new=AsyncMock(side_effect=ConnectionError("Redis unavailable")),
        ):
            await process_message(
                {"id": "AAPL", "price": 230.5},
                runtime,
            )

        self.assertEqual(runtime.quotes_received, 0)
        self.assertIsNone(runtime.last_quote_at)
        self.assertIn("Redis quote write failed", runtime.error)

    def test_daily_batch_builds_historical_quote_with_market_timestamp(self):
        index = pd.DatetimeIndex(
            ["2026-10-01 00:00:00+00:00", "2026-10-02 00:00:00+00:00"]
        )
        data = pd.DataFrame(
            {
                "Close": [98.0, 101.0],
                "Volume": [1_000, 1_500],
            },
            index=index,
        )

        with patch("assets.market_data.yf.download", return_value=data) as download:
            quotes = get_latest_daily_quotes(["AAPL"])

        download.assert_called_once()
        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0].price, 101.0)
        self.assertEqual(quotes[0].source, "daily")
        self.assertEqual(quotes[0].timestamp, index[-1].to_pydatetime())
        self.assertEqual(quotes[0].previous_close, 98.0)
        self.assertEqual(quotes[0].change, 3.0)
        self.assertEqual(quotes[0].day_volume, 1_500)

    async def test_historical_fallback_is_batch_and_does_not_overwrite_fresh_quotes(
        self,
    ):
        stale_symbols = ["AAPL", "MSFT"]
        daily_quote = LiveQuote(
            symbol="AAPL",
            price=230.0,
            timestamp=datetime.now(timezone.utc) - timedelta(days=1),
            source="daily",
        )
        with (
            patch(
                "live_market.worker.get_asset_symbols",
                new=AsyncMock(return_value=stale_symbols),
            ),
            patch(
                "live_market.worker.get_latest_quotes",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "live_market.worker.get_recent_historical_fallback_attempts",
                new=AsyncMock(return_value=set()),
            ),
            patch(
                "live_market.worker.mark_historical_fallback_attempted",
                new=AsyncMock(),
            ) as mark_attempted,
            patch(
                "live_market.worker.get_latest_daily_quotes",
                return_value=[daily_quote],
            ) as download_daily,
            patch(
                "live_market.worker.save_historical_quote_if_stale",
                new=AsyncMock(return_value=True),
            ) as save_historical,
            patch(
                "live_market.worker.asyncio.sleep",
                new=AsyncMock(side_effect=RuntimeError("stop")),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "stop"):
                await refresh_stale_historical_quotes(WorkerRuntime())

        mark_attempted.assert_awaited_once_with(stale_symbols)
        download_daily.assert_called_once_with(stale_symbols)
        save_historical.assert_awaited_once()
        self.assertEqual(save_historical.await_args.args[0], daily_quote)

    async def test_historical_fallback_fills_missing_fields_on_fresh_live_quote(
        self,
    ):
        symbols = ["AAPL"]
        live_quote = LiveQuote(
            symbol="AAPL",
            price=230.0,
            timestamp=datetime.now(timezone.utc),
            source="live",
            day_volume=1_000,
        )
        daily_quote = LiveQuote(
            symbol="AAPL",
            price=229.0,
            timestamp=datetime.now(timezone.utc) - timedelta(days=1),
            source="daily",
            day_volume=2_000,
            previous_close=228.0,
            change=1.0,
            change_percent=0.4386,
        )
        with (
            patch(
                "live_market.worker.get_asset_symbols",
                new=AsyncMock(return_value=symbols),
            ),
            patch(
                "live_market.worker.get_latest_quotes",
                new=AsyncMock(return_value={"AAPL": live_quote}),
            ),
            patch(
                "live_market.worker.get_recent_historical_fallback_attempts",
                new=AsyncMock(return_value=set()),
            ),
            patch(
                "live_market.worker.mark_historical_fallback_attempted",
                new=AsyncMock(),
            ) as mark_attempted,
            patch(
                "live_market.worker.get_latest_daily_quotes",
                return_value=[daily_quote],
            ) as download_daily,
            patch(
                "live_market.worker.save_historical_quote_if_stale",
                new=AsyncMock(return_value=True),
            ) as save_historical,
            patch(
                "live_market.worker.asyncio.sleep",
                new=AsyncMock(side_effect=RuntimeError("stop")),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "stop"):
                await refresh_stale_historical_quotes(WorkerRuntime())

        mark_attempted.assert_awaited_once_with(symbols)
        download_daily.assert_called_once_with(symbols)
        save_historical.assert_awaited_once()
        saved_quote, stale_before = save_historical.await_args.args
        self.assertEqual(saved_quote, daily_quote)
        self.assertIsInstance(stale_before, datetime)
        self.assertLess(stale_before, datetime.now(timezone.utc))

    def test_count_price_availability_splits_live_delayed_and_unavailable(self):
        now = datetime.now(timezone.utc)
        quotes = {
            "LIVE": LiveQuote(
                symbol="LIVE",
                price=10,
                timestamp=now - timedelta(seconds=30),
            ),
            "DAILY": LiveQuote(
                symbol="DAILY",
                price=11,
                timestamp=now - timedelta(days=1),
                source="daily",
            ),
            "STALE": LiveQuote(
                symbol="STALE",
                price=12,
                timestamp=now - timedelta(minutes=5),
            ),
        }

        counts = count_price_availability(
            ["LIVE", "DAILY", "STALE", "MISSING"],
            quotes,
            now,
        )

        self.assertEqual(counts, (1, 2, 1))


if __name__ == "__main__":
    unittest.main()
