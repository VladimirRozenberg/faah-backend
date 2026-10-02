import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from live_market.worker import get_asset_symbols


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


if __name__ == "__main__":
    unittest.main()
