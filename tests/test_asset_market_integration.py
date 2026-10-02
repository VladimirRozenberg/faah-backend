import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from assets.schemas import AssetSummary
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

    async def test_asset_list_uses_yahoo_fallback_when_redis_is_unavailable(self):
        asset = database_asset()
        result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [asset]))
        db = SimpleNamespace(
            scalar=AsyncMock(return_value=1),
            execute=AsyncMock(return_value=result),
            get=AsyncMock(return_value=None),
        )
        user = SimpleNamespace(user_id=3)
        fallback_summary = AssetSummary(
            symbol="AAPL",
            name="Apple",
            type="stock",
            currency="USD",
            last_price=231.0,
            previous_close=228.0,
            change=3.0,
            change_percent=1.3158,
            retrieved_at=datetime(2026, 9, 25, tzinfo=timezone.utc),
        )

        with (
            patch(
                "routers.assets.get_latest_quote",
                new=AsyncMock(side_effect=RuntimeError("Redis unavailable")),
            ),
            patch(
                "routers.assets.get_market_assets",
                return_value=[fallback_summary],
            ) as yahoo_fallback,
        ):
            response = await list_assets(
                db,
                user,
                page=1,
                page_size=20,
                search="",
            )

        yahoo_fallback.assert_called_once_with([asset])
        self.assertEqual(response.items[0].market, fallback_summary)

    async def test_asset_list_uses_yahoo_for_cache_misses_in_one_batch(self):
        assets = [database_asset(), database_asset()]
        assets[1].ast_id = 8
        assets[1].ast_symbol = "MSFT"
        assets[1].ast_name = "Microsoft"
        result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: assets))
        db = SimpleNamespace(
            scalar=AsyncMock(return_value=2),
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
        fallback_summary = AssetSummary(
            symbol="MSFT",
            name="Microsoft",
            type="stock",
            currency="USD",
            last_price=510.0,
            previous_close=505.0,
            change=5.0,
            change_percent=0.9901,
            retrieved_at=datetime(2026, 9, 25, tzinfo=timezone.utc),
        )

        async def cached_quote(symbol):
            return quote if symbol == "AAPL" else None

        with (
            patch(
                "routers.assets.get_latest_quote",
                new=AsyncMock(side_effect=cached_quote),
            ),
            patch(
                "routers.assets.get_market_assets",
                return_value=[fallback_summary],
            ) as yahoo_fallback,
        ):
            response = await list_assets(
                db,
                user,
                page=1,
                page_size=20,
                search="",
            )

        yahoo_fallback.assert_called_once_with([assets[1]])
        markets = {item.symbol: item.market for item in response.items}
        self.assertEqual(markets["AAPL"].last_price, quote.price)
        self.assertEqual(markets["AAPL"].source, "Redis live quote")
        self.assertEqual(markets["MSFT"], fallback_summary)


if __name__ == "__main__":
    unittest.main()
