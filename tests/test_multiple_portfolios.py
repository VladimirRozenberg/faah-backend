"""Integration coverage for the user-to-portfolios one-to-many relationship."""

import unittest
from decimal import Decimal

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
    PortfolioStrategist,
    User,
)
from portfolio.repository import (
    AmbiguousPortfolioError,
    create_user_portfolio,
    list_user_portfolios,
    read_user_portfolio,
)
from portfolio.schemas import PortfolioCreateRequest
from routers.assets import list_niches, router as asset_router
from routers.portfolios import router as portfolio_router


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
        niche_paths = {
            route.path
            for route in asset_router.routes
            if "GET" in getattr(route, "methods", set())
        }
        self.assertIn("/api/niches", niche_paths)


if __name__ == "__main__":
    unittest.main()
