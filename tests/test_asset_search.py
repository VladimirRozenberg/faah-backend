"""Recherche SQL sur une base de test en mémoire, sans fournisseur externe."""
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from assets.schemas import AssetSummary
from db import Base
from models import Asset, AssetNiche, Favorite, Forex, Niche, Stock, User
from routers.assets import list_assets, router


class AssetSearchTests(unittest.IsolatedAsyncioTestCase):
    def test_filter_lists_are_url_parameters_not_json_body(self):
        route = next(route for route in router.routes if route.path == "/api/assets")
        names = {parameter.name for parameter in route.dependant.query_params}
        self.assertTrue({"asset_type", "niche_id", "exchange", "country", "currency",
                         "sector", "industry", "base_currency", "quote_currency"} <= names)
        self.assertEqual(route.dependant.body_params, [])

    async def test_search_before_pagination(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as connection:
                await connection.run_sync(lambda c: Base.metadata.create_all(c, tables=[m.__table__ for m in [User, Asset, Stock, Favorite]]))
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                db.add_all([
                    Asset(ast_symbol="AAPL", ast_name="Apple Inc.", ast_type="stock"),
                    Asset(ast_symbol="APLE", ast_name="Apple Hospitality", ast_type="stock"),
                    Asset(ast_symbol="HWM", ast_name="Howmet Aerospace", ast_type="stock"),
                    Asset(ast_symbol="TEST", ast_name="100%_literal", ast_type="stock"),
                ])
                await db.commit()
                user = SimpleNamespace(user_id=1)
                market_summary = AssetSummary(
                    symbol="AAPL",
                    name="Apple Inc.",
                    type="stock",
                    currency="USD",
                    last_price=201.5,
                    previous_close=200.0,
                    change=1.5,
                    change_percent=0.75,
                    volume=1_000_000,
                    retrieved_at=datetime.now(timezone.utc),
                )
                with patch(
                    "routers.assets.get_market_assets",
                    return_value=[market_summary],
                ):
                    first = await list_assets(db, user, page=1, page_size=1, search="  APPLE  ")
                    second = await list_assets(db, user, page=2, page_size=1, search="apple")
                    self.assertEqual(first.count, 2)
                    self.assertEqual(second.count, 2)
                    self.assertEqual(len(first.items), 1)
                    self.assertNotEqual(first.items[0].id, second.items[0].id)
                    apple = await list_assets(db, user, page=1, page_size=20, search="AAPL")
                    self.assertEqual(apple.items[0].market, market_summary)
                    by_symbol = await list_assets(db, user, page=1, page_size=20, search="hwm")
                    self.assertEqual([a.symbol for a in by_symbol.items], ["HWM"])
                    literal = await list_assets(db, user, page=1, page_size=20, search="%_")
                    self.assertEqual([a.symbol for a in literal.items], ["TEST"])
                    empty = await list_assets(db, user, page=1, page_size=20, search="missing")
                    self.assertEqual(empty.count, 0)
                    self.assertEqual(empty.items, [])
                    all_assets = await list_assets(db, user, page=1, page_size=20, search="   ")
                    self.assertEqual(all_assets.count, 4)
                    assets_by_symbol = {a.symbol: a.id for a in all_assets.items}
                    db.add_all([
                        Favorite(fav_usr_id=1, fav_ast_id=assets_by_symbol["AAPL"]),
                        Favorite(fav_usr_id=1, fav_ast_id=assets_by_symbol["APLE"]),
                        Favorite(fav_usr_id=2, fav_ast_id=assets_by_symbol["HWM"]),
                    ])
                    await db.commit()
                    favorites_first = await list_assets(db, user, page=1, page_size=1, search="apple", favorites_only=True)
                    favorites_second = await list_assets(db, user, page=2, page_size=1, search="apple", favorites_only=True)
                    self.assertEqual(favorites_first.count, 2)
                    self.assertEqual(favorites_second.count, 2)
                    self.assertEqual(len(favorites_first.items), 1)
                    self.assertEqual(len(favorites_second.items), 1)
                    self.assertNotEqual(favorites_first.items[0].id, favorites_second.items[0].id)
                    favorites = await list_assets(db, user, page=1, page_size=20, search="", favorites_only=True)
                    self.assertEqual(favorites.count, 2)
                    self.assertEqual({a.symbol for a in favorites.items}, {"AAPL", "APLE"})
                    other_user = await list_assets(db, SimpleNamespace(user_id=2), page=1, page_size=20, search="", favorites_only=True)
                    self.assertEqual([a.symbol for a in other_user.items], ["HWM"])
                    no_favorites = await list_assets(db, SimpleNamespace(user_id=3), page=1, page_size=20, search="", favorites_only=True)
                    self.assertEqual(no_favorites.count, 0)
                    self.assertEqual(no_favorites.items, [])
                    unmatched = await list_assets(db, user, page=1, page_size=20, search="hwm", favorites_only=True)
                    self.assertEqual(unmatched.count, 0)
                    self.assertEqual(unmatched.items, [])
                    unfiltered = await list_assets(db, user, page=1, page_size=20, search="", favorites_only=False)
                    self.assertEqual(unfiltered.count, 4)
        finally:
            await engine.dispose()

    async def test_catalog_filters_compose_before_pagination(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            tables = [
                User,
                Asset,
                AssetNiche,
                Favorite,
                Forex,
                Niche,
                Stock,
            ]
            async with engine.begin() as connection:
                await connection.run_sync(
                    lambda sync_connection: Base.metadata.create_all(
                        sync_connection,
                        tables=[model.__table__ for model in tables],
                    )
                )

            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                apple = Asset(
                    ast_symbol="AAPL",
                    ast_name="Apple Inc.",
                    ast_type="stock",
                    ast_exchange="NMS",
                    ast_country="United States",
                    ast_currency="USD",
                )
                euro_dollar = Asset(
                    ast_symbol="EURUSD=X",
                    ast_name="EUR/USD",
                    ast_type="forex",
                    ast_exchange="CCY",
                    ast_country="United States",
                    ast_currency="USD",
                )
                niche = Niche(
                    nic_name="Enterprise Software",
                    nic_category="Technology & AI",
                    nic_description="Enterprise software companies",
                )
                db.add_all([apple, euro_dollar, niche])
                await db.flush()
                db.add_all(
                    [
                        Stock(
                            sto_ast_id=apple.ast_id,
                            sto_sector="Technology",
                            sto_industry="Software",
                        ),
                        Forex(
                            for_ast_id=euro_dollar.ast_id,
                            for_base_currency="EUR",
                            for_quote_currency="USD",
                        ),
                        AssetNiche(
                            ani_ast_id=apple.ast_id,
                            ani_nic_id=niche.nic_id,
                        ),
                    ]
                )
                await db.commit()

                with patch("routers.assets.get_market_assets", return_value=[]):
                    # Une saisie incomplète fonctionne aussi sur les pages suivantes.
                    partial = await list_assets(
                        db, SimpleNamespace(user_id=1), page=2, page_size=1,
                        search="", country=["un"], currency=["us"],
                    )
                    self.assertEqual(partial.count, 2)
                    self.assertEqual(len(partial.items), 1)
                    literal = await list_assets(
                        db, SimpleNamespace(user_id=1), page=1, page_size=20,
                        search="", country=["%_"],
                    )
                    self.assertEqual(literal.count, 0)
                    stock_results = await list_assets(
                        db,
                        SimpleNamespace(user_id=1),
                        page=1,
                        page_size=20,
                        search="",
                        asset_type=["stock"],
                        niche_id=[niche.nic_id],
                        exchange=["nm"],
                        country=["uNi"],
                        currency=["us"],
                        sector=["Technology"],
                        industry=["Software"],
                    )
                    forex_results = await list_assets(
                        db,
                        SimpleNamespace(user_id=1),
                        page=1,
                        page_size=20,
                        search="",
                        asset_type=["forex"],
                        base_currency=["EUR"],
                        quote_currency=["USD"],
                    )

                self.assertEqual(stock_results.count, 1)
                self.assertEqual([item.symbol for item in stock_results.items], ["AAPL"])
                self.assertEqual(forex_results.count, 1)
                self.assertEqual([item.symbol for item in forex_results.items], ["EURUSD=X"])
        finally:
            await engine.dispose()
