"""Règles de compatibilité : pas d'appel marché et aucune base réelle."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from portfolio.repository import check_trade_portfolio, buy_asset, sell_asset
from portfolio.schemas import BuyAssetRequest, SellAssetRequest


class TradePortfolioRulesTests(unittest.IsolatedAsyncioTestCase):
    def database(self, types):
        result = MagicMock()
        result.all.return_value = types
        return SimpleNamespace(scalars=AsyncMock(return_value=result))

    async def test_compatible_and_unrestricted(self):
        portfolio = SimpleNamespace(prt_id=10, prt_is_active=True, prt_base_currency="USD")
        asset = SimpleNamespace(ast_type="crypto")
        for types in [[], ["crypto"], ["stock", "crypto"]]:
            await check_trade_portfolio(self.database(types), portfolio, asset)
        with self.assertRaisesRegex(ValueError, "asset type"):
            await check_trade_portfolio(self.database(["stock"]), portfolio, asset)

    async def test_paused_and_non_usd_rejected(self):
        for active, currency in [(False, "USD"), (True, "EUR")]:
            portfolio = SimpleNamespace(prt_id=10, prt_is_active=active, prt_base_currency=currency)
            with self.assertRaises(ValueError):
                await check_trade_portfolio(self.database([]), portfolio, SimpleNamespace(ast_type="crypto"))

    async def test_buy_and_sell_check_before_changing_positions(self):
        portfolio = SimpleNamespace(prt_id=10, prt_is_active=True, prt_base_currency="USD")
        asset = SimpleNamespace(ast_type="crypto")
        for operation, data in [
            (buy_asset, BuyAssetRequest(symbol="BTC-USD", quantity=1, purchase_price=100)),
            (sell_asset, SellAssetRequest(symbol="BTC-USD", quantity=1, sale_price=100)),
        ]:
            db = self.database(["stock"])
            with patch("portfolio.repository.get_active_account", AsyncMock()), \
                 patch("portfolio.repository.get_user_portfolio", AsyncMock(return_value=portfolio)), \
                 patch("portfolio.repository.find_asset", AsyncMock(return_value=asset)), \
                 patch("portfolio.repository.execution_price", AsyncMock()) as price:
                with self.assertRaisesRegex(ValueError, "asset type"):
                    await operation(db, 42, data, 10)
                price.assert_not_awaited()
