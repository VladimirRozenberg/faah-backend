"""Integration coverage for the user-to-portfolios one-to-many relationship."""

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db import Base
from models import (
    Asset,
    Niche,
    Portfolio,
    PortfolioAsset,
    PortfolioAssetTypePreference,
    PortfolioNichePreference,
    PortfolioRecommendation,
    PortfolioStrategist,
    User,
)
from portfolio.repository import (
    AmbiguousPortfolioError,
    create_user_portfolio,
    list_user_portfolios,
    read_user_asset_value,
    read_user_portfolio,
    update_user_portfolio,
)
from portfolio.schemas import PortfolioCreateRequest, PortfolioUpdateRequest
from routers.assets import list_niches, router as asset_router
from routers.portfolios import (
    get_user_available_cash,
    get_user_portfolios,
    get_user_recent_recommendations,
    get_portfolio_recommendations,
    router as portfolio_router,
)


class MultiplePortfolioTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        tables = [
            model.__table__
            for model in [
                User,
                Asset,
                Niche,
                Portfolio,
                PortfolioAssetTypePreference,
                PortfolioNichePreference,
                PortfolioAsset,
                PortfolioStrategist,
                PortfolioRecommendation,
            ]
        ]
        async with self.engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: Base.metadata.create_all(
                    sync_connection,
                    tables=tables,
                )
            )
        self.session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
        )

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_user_can_own_multiple_portfolios_with_one_strategist_each(self):
        async with self.session_factory() as db:
            user = User(
                usr_username="multi-portfolio-user",
                usr_email="multi@example.com",
                usr_password_hash="not-used-in-this-test",
                usr_balance=Decimal("10000"),
            )
            ai_niche = Niche(
                nic_name="Artificial Intelligence",
                nic_category="Technology & AI",
                nic_description="AI businesses",
            )
            db.add_all([user, ai_niche])
            await db.commit()

            conservative = await create_user_portfolio(
                db,
                user.usr_id,
                PortfolioCreateRequest(
                    name="Conservative",
                    strategy_type="income",
                    risk_tolerance="low",
                ),
            )
            growth = await create_user_portfolio(
                db,
                user.usr_id,
                PortfolioCreateRequest(
                    name="Growth",
                    strategy_type="growth",
                    risk_tolerance="high",
                    preferred_asset_types=["stock", "crypto"],
                    preferred_niche_ids=[ai_niche.nic_id],
                ),
            )

            self.assertNotEqual(conservative.id, growth.id)
            self.assertEqual(conservative.user_id, user.usr_id)
            self.assertEqual(growth.user_id, user.usr_id)
            self.assertEqual(growth.preferred_asset_types, ["crypto", "stock"])
            self.assertEqual(growth.preferred_niche_ids, [ai_niche.nic_id])

            portfolios = await list_user_portfolios(db, user.usr_id)
            self.assertEqual(portfolios.count, 2)
            self.assertEqual(
                {item.name for item in portfolios.items},
                {"Conservative", "Growth"},
            )

            strategist_count = await db.scalar(
                select(func.count(PortfolioStrategist.pst_id))
            )
            self.assertEqual(strategist_count, 2)

            selected = await read_user_portfolio(db, user.usr_id, growth.id)
            self.assertEqual(selected.id, growth.id)
            self.assertEqual(selected.strategy_type, "growth")

            with self.assertRaisesRegex(
                AmbiguousPortfolioError,
                "specify portfolio_id",
            ):
                await read_user_portfolio(db, user.usr_id)

    async def test_portfolio_list_returns_summary_with_return_and_status(self):
        async with self.session_factory() as db:
            user = User(
                usr_username="summary-user",
                usr_email="summary@example.com",
                usr_password_hash="not-used-in-this-test",
            )
            db.add(user)
            await db.commit()

            invested = await create_user_portfolio(
                db,
                user.usr_id,
                PortfolioCreateRequest(name="Invested", risk_tolerance="high"),
            )
            empty = await create_user_portfolio(
                db,
                user.usr_id,
                PortfolioCreateRequest(name="Paused"),
            )
            paused = await db.get(Portfolio, empty.id)
            paused.prt_is_active = False
            asset = Asset(
                ast_symbol="AAPL",
                ast_name="Apple",
                ast_type="stock",
                ast_currency="USD",
            )
            db.add(asset)
            await db.flush()
            db.add(
                PortfolioAsset(
                    pas_prt_id=invested.id,
                    pas_ast_id=asset.ast_id,
                    pas_quantity=Decimal("2"),
                    pas_average_purchase_price=Decimal("100"),
                )
            )
            await db.commit()

            with patch(
                "portfolio.repository.get_current_price",
                new=AsyncMock(return_value=110.0),
            ):
                result = await get_user_portfolios(user.usr_id, db)

            self.assertEqual(result.count, 2)
            by_name = {item.name: item for item in result.items}
            self.assertEqual(by_name["Invested"].portfolio_id, invested.id)
            self.assertEqual(by_name["Invested"].risk_tolerance, "high")
            self.assertEqual(by_name["Invested"].return_pct, 10.0)
            self.assertEqual(by_name["Invested"].status, "active")
            self.assertIsNone(by_name["Paused"].return_pct)
            self.assertEqual(by_name["Paused"].status, "paused")
            self.assertNotIn("positions", by_name["Invested"].model_dump())

    async def test_portfolio_update_can_pause_without_resetting_configuration(self):
        async with self.session_factory() as db:
            user = User(
                usr_username="pause-update-user",
                usr_email="pause-update@example.com",
                usr_password_hash="not-used-in-this-test",
            )
            niche = Niche(
                nic_name="Update niche",
                nic_category="Technology",
                nic_description="Portfolio update test niche",
            )
            db.add_all([user, niche])
            await db.commit()

            created = await create_user_portfolio(
                db,
                user.usr_id,
                PortfolioCreateRequest(
                    name="Configured",
                    description="Keep this description",
                    risk_tolerance="high",
                    preferred_asset_types=["stock"],
                    preferred_niche_ids=[niche.nic_id],
                ),
            )

            paused = await update_user_portfolio(
                db,
                user.usr_id,
                created.id,
                PortfolioUpdateRequest(is_active=False),
            )

            self.assertFalse(paused.is_active)
            self.assertEqual(paused.name, "Configured")
            self.assertEqual(paused.description, "Keep this description")
            self.assertEqual(paused.risk_tolerance, "high")
            self.assertEqual(paused.preferred_asset_types, ["stock"])
            self.assertEqual(paused.preferred_niche_ids, [niche.nic_id])

    async def test_user_without_portfolios_gets_empty_list(self):
        async with self.session_factory() as db:
            user = User(
                usr_username="empty-user",
                usr_email="empty@example.com",
                usr_password_hash="not-used-in-this-test",
            )
            db.add(user)
            await db.commit()

            result = await get_user_portfolios(user.usr_id, db)

            self.assertEqual(result.model_dump(), {"count": 0, "items": []})

    async def test_recent_recommendations_preserve_rows_actions_and_ownership(self):
        async with self.session_factory() as db:
            owner = User(
                usr_username="recommendation-owner",
                usr_email="recommendation-owner@example.com",
                usr_password_hash="not-used-in-this-test",
            )
            other = User(
                usr_username="recommendation-other",
                usr_email="recommendation-other@example.com",
                usr_password_hash="not-used-in-this-test",
            )
            db.add_all([owner, other])
            await db.commit()
            owned_portfolio = await create_user_portfolio(
                db, owner.usr_id, PortfolioCreateRequest(name="Owned")
            )
            other_portfolio = await create_user_portfolio(
                db, other.usr_id, PortfolioCreateRequest(name="Other")
            )
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            recommendations = [
                PortfolioRecommendation(
                    prc_psr_id=1,
                    prc_prt_id=owned_portfolio.id,
                    prc_kind="holding_assessment",
                    prc_action="bad",
                    prc_reason="Risk increased.",
                    prc_status="viewed",
                    prc_created_at=now - timedelta(minutes=45),
                    prc_updated_at=now - timedelta(minutes=45),
                ),
                PortfolioRecommendation(
                    prc_psr_id=2,
                    prc_prt_id=owned_portfolio.id,
                    prc_kind="targeted_conclusion",
                    prc_action="no_action",
                    prc_reason="No change is needed.",
                    prc_status="new",
                    prc_created_at=now - timedelta(minutes=20),
                    prc_updated_at=now - timedelta(minutes=20),
                ),
                PortfolioRecommendation(
                    prc_psr_id=3,
                    prc_prt_id=owned_portfolio.id,
                    prc_kind="opportunity",
                    prc_asset_symbol="NVDA",
                    prc_action="opportunity",
                    prc_reason="A possible opportunity.",
                    prc_confidence=80,
                    prc_status="dismissed",
                    prc_created_at=now - timedelta(minutes=10),
                    prc_updated_at=now - timedelta(minutes=10),
                ),
                PortfolioRecommendation(
                    prc_psr_id=4,
                    prc_prt_id=owned_portfolio.id,
                    prc_kind="opportunity",
                    prc_asset_symbol="NVDA",
                    prc_action="opportunity",
                    prc_reason="A separate strategist output.",
                    prc_confidence=75,
                    prc_status="new",
                    prc_created_at=now - timedelta(minutes=5),
                    prc_updated_at=now - timedelta(minutes=5),
                ),
                PortfolioRecommendation(
                    prc_psr_id=5,
                    prc_prt_id=owned_portfolio.id,
                    prc_kind="opportunity",
                    prc_action="watch",
                    prc_reason="Still within the recent window.",
                    prc_status="new",
                    prc_created_at=now - timedelta(minutes=59),
                    prc_updated_at=now - timedelta(minutes=59),
                ),
                PortfolioRecommendation(
                    prc_psr_id=6,
                    prc_prt_id=owned_portfolio.id,
                    prc_kind="opportunity",
                    prc_action="opportunity",
                    prc_reason="Too old.",
                    prc_status="new",
                    prc_created_at=now - timedelta(minutes=61),
                    prc_updated_at=now - timedelta(minutes=61),
                ),
                PortfolioRecommendation(
                    prc_psr_id=7,
                    prc_prt_id=other_portfolio.id,
                    prc_kind="opportunity",
                    prc_action="opportunity",
                    prc_reason="Belongs to another user.",
                    prc_status="new",
                    prc_created_at=now,
                    prc_updated_at=now,
                ),
                PortfolioRecommendation(
                    prc_psr_id=8,
                    prc_prt_id=owned_portfolio.id,
                    prc_kind="holding_assessment",
                    prc_action="unchanged",
                    prc_reason="Created inside the one-hour window.",
                    prc_status="new",
                    prc_created_at=now - timedelta(minutes=59),
                    prc_updated_at=now - timedelta(minutes=59),
                ),
            ]
            db.add_all(recommendations)
            await db.commit()

            result = await get_user_recent_recommendations(
                owner.usr_id,
                db,
                within=None,
                kind=None,
                status_filter=None,
            )

            self.assertEqual(result.count, 7)
            self.assertEqual(
                [item.run_id for item in result.items],
                [4, 3, 2, 1, 8, 5, 6],
                [(item.run_id, item.created_at) for item in result.items],
            )
            self.assertEqual(
                {item.kind for item in result.items},
                {"opportunity", "holding_assessment", "targeted_conclusion"},
            )
            self.assertEqual(result.items[0].action, "opportunity")
            self.assertEqual(result.items[2].action, "no_action")
            self.assertEqual(result.items[3].action, "bad")
            self.assertEqual(result.items[0].portfolio_name, "Owned")
            self.assertEqual(result.items[0].recommendation_id, recommendations[3].prc_id)

            within_one_hour = await get_user_recent_recommendations(
                owner.usr_id,
                db,
                within="1h",
                kind=None,
                status_filter=None,
            )
            by_kind = await get_user_recent_recommendations(
                owner.usr_id,
                db,
                within=None,
                kind="opportunity",
                status_filter=None,
            )
            by_status = await get_user_recent_recommendations(
                owner.usr_id,
                db,
                within=None,
                kind=None,
                status_filter="new",
            )
            by_both = await get_user_recent_recommendations(
                owner.usr_id,
                db,
                within=None,
                kind="opportunity",
                status_filter="new",
            )
            second_page = await get_portfolio_recommendations(
                owner.usr_id,
                owned_portfolio.id,
                db,
                within=None,
                kind=None,
                status_filter=None,
                page=2,
                page_size=2,
            )
            self.assertEqual(within_one_hour.count, 6)
            self.assertEqual(
                [item.run_id for item in within_one_hour.items],
                [4, 3, 2, 1, 8, 5],
            )
            self.assertEqual(by_kind.count, 4)
            self.assertEqual(by_status.count, 5)
            self.assertEqual(by_both.count, 3)
            self.assertEqual(
                [item.run_id for item in by_both.items],
                [4, 5, 6],
            )
            self.assertEqual(second_page.count, 7)
            self.assertEqual(second_page.page, 2)
            self.assertEqual(second_page.page_size, 2)
            self.assertEqual([item.run_id for item in second_page.items], [2, 1])
            with self.assertRaises(HTTPException) as not_owned:
                await get_portfolio_recommendations(
                    owner.usr_id,
                    other_portfolio.id,
                    db,
                    within=None,
                    kind=None,
                    status_filter=None,
                    page=1,
                    page_size=20,
                )
            self.assertEqual(not_owned.exception.status_code, 404)

    async def test_recent_recommendations_reject_missing_or_disabled_users(self):
        async with self.session_factory() as db:
            with self.assertRaises(HTTPException) as missing:
                await get_user_recent_recommendations(999, db)
            self.assertEqual(missing.exception.status_code, 404)

            user = User(
                usr_username="disabled-recommendation-user",
                usr_email="disabled-recommendation@example.com",
                usr_password_hash="not-used-in-this-test",
                usr_is_active=False,
            )
            db.add(user)
            await db.commit()

            with self.assertRaises(HTTPException) as disabled:
                await get_user_recent_recommendations(user.usr_id, db)
            self.assertEqual(disabled.exception.status_code, 404)

    async def test_available_cash_endpoint_returns_user_balance_once(self):
        async with self.session_factory() as db:
            user = User(
                usr_username="cash-user",
                usr_email="cash@example.com",
                usr_password_hash="not-used-in-this-test",
                usr_balance=Decimal("1234.56"),
            )
            db.add(user)
            await db.commit()

            result = await get_user_available_cash(user.usr_id, db)

            self.assertEqual(result.user_id, user.usr_id)
            self.assertEqual(result.currency, "USD")
            self.assertEqual(result.available_cash, 1234.56)

        get_paths = {
            route.path
            for route in portfolio_router.routes
            if "GET" in getattr(route, "methods", set())
        }
        self.assertIn("/api/users/{user_id}/available-cash", get_paths)

    async def test_user_asset_value_aggregates_assets_across_portfolios(self):
        async with self.session_factory() as db:
            user = User(
                usr_username="valuation-user",
                usr_email="valuation@example.com",
                usr_password_hash="not-used-in-this-test",
            )
            db.add(user)
            await db.commit()
            first = await create_user_portfolio(
                db,
                user.usr_id,
                PortfolioCreateRequest(name="First"),
            )
            second = await create_user_portfolio(
                db,
                user.usr_id,
                PortfolioCreateRequest(name="Second"),
            )
            apple = Asset(
                ast_symbol="AAPL",
                ast_name="Apple",
                ast_type="stock",
                ast_currency="USD",
            )
            microsoft = Asset(
                ast_symbol="MSFT",
                ast_name="Microsoft",
                ast_type="stock",
                ast_currency="USD",
            )
            db.add_all([apple, microsoft])
            await db.flush()
            db.add_all(
                [
                    PortfolioAsset(
                        pas_prt_id=first.id,
                        pas_ast_id=apple.ast_id,
                        pas_quantity=Decimal("2"),
                        pas_average_purchase_price=Decimal("100"),
                    ),
                    PortfolioAsset(
                        pas_prt_id=second.id,
                        pas_ast_id=apple.ast_id,
                        pas_quantity=Decimal("3"),
                        pas_average_purchase_price=Decimal("120"),
                    ),
                    PortfolioAsset(
                        pas_prt_id=second.id,
                        pas_ast_id=microsoft.ast_id,
                        pas_quantity=Decimal("1"),
                        pas_average_purchase_price=Decimal("200"),
                    ),
                ]
            )
            await db.commit()

            async def price(asset):
                return {"AAPL": 150.0, "MSFT": 300.0}[asset.ast_symbol]

            with patch(
                "portfolio.repository.get_current_price",
                new=AsyncMock(side_effect=price),
            ) as market_price:
                result = await read_user_asset_value(db, user.usr_id)

            self.assertEqual(result.portfolios_count, 2)
            self.assertEqual(result.assets_count, 2)
            self.assertEqual(result.total_invested, 760.0)
            self.assertEqual(result.total_current_value, 1050.0)
            self.assertEqual(result.total_profit_loss, 290.0)
            self.assertTrue(result.valuation_complete)
            self.assertEqual(result.missing_price_symbols, [])
            self.assertEqual(market_price.await_count, 2)
            apple_value = next(
                item for item in result.assets if item.symbol == "AAPL"
            )
            self.assertEqual(apple_value.portfolios_count, 2)
            self.assertEqual(apple_value.total_quantity, 5.0)
            self.assertEqual(apple_value.invested_amount, 560.0)
            self.assertEqual(apple_value.current_value, 750.0)

    async def test_user_asset_value_marks_missing_quotes_incomplete(self):
        async with self.session_factory() as db:
            user = User(
                usr_username="missing-price-user",
                usr_email="missing-price@example.com",
                usr_password_hash="not-used-in-this-test",
            )
            db.add(user)
            await db.commit()
            portfolio = await create_user_portfolio(
                db,
                user.usr_id,
                PortfolioCreateRequest(name="Only"),
            )
            asset = Asset(
                ast_symbol="AAPL",
                ast_name="Apple",
                ast_type="stock",
                ast_currency="USD",
            )
            db.add(asset)
            await db.flush()
            db.add(
                PortfolioAsset(
                    pas_prt_id=portfolio.id,
                    pas_ast_id=asset.ast_id,
                    pas_quantity=Decimal("2"),
                    pas_average_purchase_price=Decimal("100"),
                )
            )
            await db.commit()

            with patch(
                "portfolio.repository.get_current_price",
                new=AsyncMock(return_value=None),
            ):
                result = await read_user_asset_value(db, user.usr_id)

            self.assertFalse(result.valuation_complete)
            self.assertEqual(result.missing_price_symbols, ["AAPL"])
            self.assertIsNone(result.total_current_value)
            self.assertIsNone(result.total_profit_loss)
            self.assertIsNone(result.assets[0].current_value)

    async def test_user_cannot_read_another_users_portfolio(self):
        async with self.session_factory() as db:
            owner = User(
                usr_username="owner",
                usr_email="owner@example.com",
                usr_password_hash="not-used-in-this-test",
            )
            other = User(
                usr_username="other",
                usr_email="other@example.com",
                usr_password_hash="not-used-in-this-test",
            )
            db.add_all([owner, other])
            await db.commit()

            portfolio = await create_user_portfolio(
                db,
                owner.usr_id,
                PortfolioCreateRequest(name="Owner only"),
            )

            with self.assertRaisesRegex(LookupError, "does not exist"):
                await read_user_portfolio(db, other.usr_id, portfolio.id)

    def test_create_request_accepts_only_supported_v1_configuration(self):
        data = PortfolioCreateRequest(name="Balanced", strategy_type="balanced")
        self.assertEqual(data.base_currency, "USD")
        self.assertEqual(PortfolioCreateRequest(name="  Trimmed  ").name, "Trimmed")

        with self.assertRaises(ValidationError):
            PortfolioCreateRequest(name="Invalid", strategy_type="day-trading")

        with self.assertRaises(ValidationError):
            PortfolioCreateRequest(name="Invalid", base_currency="EUR")

        with self.assertRaises(ValidationError):
            PortfolioCreateRequest(name="   ")

        with self.assertRaises(ValidationError):
            PortfolioCreateRequest(
                name="Invalid",
                preferred_asset_types=["stock", "stock"],
            )

        with self.assertRaises(ValidationError):
            PortfolioCreateRequest(name="Invalid", preferred_niche_ids=[0])

    async def test_create_rejects_an_unknown_preferred_niche(self):
        async with self.session_factory() as db:
            user = User(
                usr_username="unknown-niche-user",
                usr_email="unknown-niche@example.com",
                usr_password_hash="not-used-in-this-test",
            )
            db.add(user)
            await db.commit()

            with self.assertRaisesRegex(ValueError, "Unknown preferred niche IDs: 999"):
                await create_user_portfolio(
                    db,
                    user.usr_id,
                    PortfolioCreateRequest(
                        name="Invalid preference",
                        preferred_niche_ids=[999],
                    ),
                )

    async def test_niche_catalog_returns_frontend_options(self):
        async with self.session_factory() as db:
            db.add_all(
                [
                    Niche(
                        nic_name="AI Hardware",
                        nic_category="Technology & AI",
                        nic_description="Processors and accelerators",
                    ),
                    Niche(
                        nic_name="Banking",
                        nic_category="Financials",
                        nic_description="Banks and financial services",
                    ),
                ]
            )
            await db.commit()

            response = await list_niches(db)

            self.assertEqual(response.count, 2)
            self.assertEqual(
                [item.name for item in response.items],
                ["Banking", "AI Hardware"],
            )

    def test_create_route_uses_explicit_portfolio_create_path(self):
        post_paths = {
            route.path
            for route in portfolio_router.routes
            if "POST" in getattr(route, "methods", set())
        }
        self.assertIn(
            "/api/users/{user_id}/portfolio/create",
            post_paths,
        )
        self.assertNotIn("/api/users/{user_id}/portfolios", post_paths)
        get_paths = {
            route.path
            for route in portfolio_router.routes
            if "GET" in getattr(route, "methods", set())
        }
        self.assertIn("/api/users/{user_id}/portfolios", get_paths)
        self.assertIn("/api/users/{user_id}/asset-value", get_paths)
        niche_paths = {
            route.path
            for route in asset_router.routes
            if "GET" in getattr(route, "methods", set())
        }
        self.assertIn("/api/niches", niche_paths)


if __name__ == "__main__":
    unittest.main()
