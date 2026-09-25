import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from assets.market_data import MarketDataUnavailableError
from assets.schemas import AssetSummary
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
        summary = AssetSummary(
            symbol="AAPL",
            name="Apple",
            type="stock",
            exchange="NASDAQ",
            currency="USD",
            last_price=230.0,
            previous_close=228.0,
            change=2.0,
            change_percent=0.8772,
            volume=1_000,
            retrieved_at=datetime(2026, 9, 25, tzinfo=timezone.utc),
        )

        with patch(
            "routers.assets.get_market_assets",
            return_value=[summary],
        ) as market:
            response = await list_assets(db, user, page=1, page_size=20)

        market.assert_called_once_with([asset])
        self.assertEqual(response.items[0].market, summary)

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
            "routers.assets.get_market_assets",
            side_effect=MarketDataUnavailableError("Yahoo unavailable"),
        ):
            response = await list_assets(db, user, page=1, page_size=20)

        self.assertEqual(response.items[0].symbol, "AAPL")
        self.assertIsNone(response.items[0].market)


if __name__ == "__main__":
    unittest.main()
