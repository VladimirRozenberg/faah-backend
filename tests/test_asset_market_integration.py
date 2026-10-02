import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from live_market.market_schemas import LiveQuote
from routers.assets import list_assets


def database_asset():
    now = datetime(2026, 9, 25, tzinfo=timezone.utc)
    return SimpleNamespace(
        ast_id=7,
        ast_symbol="AAPL",
        ast_name="Apple",
        ast_type="stock",
        ast_yahoo_type="EQUITY",
        ast_logo_mime_type=None,
        ast_exchange="NASDAQ",
        ast_currency="USD",
        ast_country="US",
        ast_is_tracked=True,
        ast_created_at=now,
        ast_updated_at=now,
    )


class AssetMarketIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_asset_list_includes_market_information(self):
        asset = database_asset()
        result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [asset]))
        db = SimpleNamespace(
            scalar=AsyncMock(return_value=1),
            execute=AsyncMock(return_value=result),
            get=AsyncMock(return_value=None),
        )
        user = SimpleNamespace(user_id=3)
        quote = LiveQuote(
            symbol="AAPL",
            price=230.0,
            timestamp=datetime(2026, 9, 25, tzinfo=timezone.utc),
            day_volume=1_000,
        )

        with patch(
            "routers.assets.get_latest_quote",
            new=AsyncMock(return_value=quote),
        ) as cached_quote:
            response = await list_assets(
                db,
                user,
                page=1,
                page_size=20,
                search="",
            )

        cached_quote.assert_awaited_once_with("AAPL")
        self.assertEqual(response.items[0].market.last_price, quote.price)
        self.assertEqual(response.items[0].market.retrieved_at, quote.timestamp)
        self.assertIsNone(response.items[0].market.previous_close)
        self.assertEqual(response.items[0].market.source, "Redis live quote")

    async def test_asset_list_survives_market_provider_failure(self):
        asset = database_asset()
        result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [asset]))
        db = SimpleNamespace(
            scalar=AsyncMock(return_value=1),
            execute=AsyncMock(return_value=result),
            get=AsyncMock(return_value=None),
        )
        user = SimpleNamespace(user_id=3)

        with patch(
            "routers.assets.get_latest_quote",
            new=AsyncMock(side_effect=RuntimeError("Redis unavailable")),
        ):
            response = await list_assets(
                db,
                user,
                page=1,
                page_size=20,
                search="",
            )

        self.assertEqual(response.items[0].symbol, "AAPL")
        self.assertIsNone(response.items[0].market)


if __name__ == "__main__":
    unittest.main()
