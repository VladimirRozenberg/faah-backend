"""Calculs USD et cache Frankfurter sans appel externe ni base réelle."""
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from portfolio import exchange_rates as fx
from portfolio.repository import get_usd_quote, buy_asset, sell_asset
from portfolio.schemas import BuyAssetRequest, SellAssetRequest


class ExchangeRateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fx._cache.clear()
        fx._locks.clear()
        fx._failures.clear()

    def response(self):
        return httpx.Response(200, request=httpx.Request("GET", "https://test/"),
            json=dict(base="CHF", quote="USD", rate=1.2,
                      date=datetime.now(timezone.utc).date().isoformat()))

    async def test_cache_concurrency_and_subunits(self):
        with patch("portfolio.exchange_rates.httpx.AsyncClient") as client:
            get = client.return_value.__aenter__.return_value.get
            get.return_value = self.response()
            rates = await asyncio.gather(*(fx.get_usd_rate("CHF") for _ in range(10)))
            self.assertTrue(all(r.factor == Decimal("1.2") for r in rates))
            self.assertEqual(get.await_count, 1)
            await fx.get_usd_rate("CHF")
            self.assertEqual(get.await_count, 1)
            fx._cache["CHF"] = (0, rates[0])
            await fx.get_usd_rate("CHF")
            self.assertEqual(get.await_count, 2)
            self.assertEqual((await fx.get_usd_rate("USD")).factor, 1)
            self.assertEqual(get.await_count, 2)
        self.assertEqual(fx.normalize_currency("GBp"), ("GBP", Decimal("0.01")))
        self.assertEqual(fx.normalize_currency("ZAc"), ("ZAR", Decimal("0.01")))
        with self.assertRaises(ValueError):
            fx.normalize_currency("")

    async def test_failure_is_not_a_fake_rate(self):
        with patch("portfolio.exchange_rates.httpx.AsyncClient") as client:
            get = client.return_value.__aenter__.return_value.get
            get.side_effect = httpx.ConnectError("offline")
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, "conversion unavailable"):
                    await fx.get_usd_rate("CHF")
            self.assertEqual(get.await_count, 1)
        data = self.response().json()
        for invalid in [None, [], data | {"base": None}, data | {"date": None}]:
            with self.assertRaises(ValueError):
                fx.parse_rate(invalid, "CHF")
        for updates in [
            {"rate": 0}, {"rate": "NaN"}, {"quote": "EUR"},
            {"date": (datetime.now(timezone.utc).date() - timedelta(days=8)).isoformat()}
        ]:
            with self.assertRaises(ValueError):
                fx.parse_rate(data | updates, "CHF")

    async def test_local_price_to_usd(self):
        asset = SimpleNamespace(ast_symbol="TEST", ast_currency="CHF")
        rate = fx.UsdRate(Decimal("1.2"), datetime.now(timezone.utc).date())
        with patch("portfolio.repository.get_native_price", AsyncMock(return_value=100)), \
             patch("portfolio.repository.get_usd_rate", AsyncMock(return_value=rate)):
            quote = await get_usd_quote(asset)
        self.assertEqual(quote["original_price"], 100)
        self.assertEqual(quote["price_usd"], 120)
        self.assertEqual(quote["price_usd"] * 3, 360)

    async def test_transactions_and_holdings_use_usd(self):
        asset = SimpleNamespace(ast_id=7, ast_symbol="TEST", ast_currency="CHF", ast_is_tracked=True)
        portfolio = SimpleNamespace(prt_id=10)
        account = SimpleNamespace(usr_balance=Decimal("500"))
        position = SimpleNamespace(pas_quantity=Decimal("0"), pas_average_purchase_price=Decimal("0"),
                                   pas_is_active=False)
        db = SimpleNamespace(get=AsyncMock(return_value=position))
        rate = fx.UsdRate(Decimal("1.2"), datetime.now(timezone.utc).date())
        with patch("portfolio.repository.get_active_account", AsyncMock(return_value=account)), \
             patch("portfolio.repository.get_user_portfolio", AsyncMock(return_value=portfolio)), \
             patch("portfolio.repository.find_asset", AsyncMock(return_value=asset)), \
             patch("portfolio.repository.check_trade_portfolio", AsyncMock()), \
             patch("portfolio.repository.get_native_price", AsyncMock(return_value=100)), \
             patch("portfolio.repository.get_usd_rate", AsyncMock(return_value=rate)), \
             patch("portfolio.repository.save_portfolio_transaction", AsyncMock()) as save:
            await buy_asset(db, 42, BuyAssetRequest(symbol="TEST", quantity=3, purchase_price=1), 10)
            self.assertEqual(account.usr_balance, 140)
            self.assertEqual(position.pas_average_purchase_price, 120)
            self.assertEqual(save.call_args.args[-1], 120)
            await sell_asset(db, 42, SellAssetRequest(symbol="TEST", quantity=1, sale_price=1), 10)
            self.assertEqual(account.usr_balance, 260)
            self.assertEqual(position.pas_quantity, 2)
            with self.assertRaisesRegex(ValueError, "Insufficient"):
                await buy_asset(db, 42, BuyAssetRequest(symbol="TEST", quantity=3, purchase_price=1), 10)
            self.assertEqual(account.usr_balance, 260)
