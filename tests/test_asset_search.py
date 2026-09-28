"""Recherche SQL sur une base de test en mémoire, sans fournisseur externe."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db import Base
from models import Asset, Favorite, Stock, User
from routers.assets import list_assets


class AssetSearchTests(unittest.IsolatedAsyncioTestCase):
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
                # Le test exerce la vraie requête SQL, mais ne charge aucun cours.
                with patch("routers.assets.add_market_information", AsyncMock()):
                    first = await list_assets(db, user, page=1, page_size=1, search="  APPLE  ")
                    second = await list_assets(db, user, page=2, page_size=1, search="apple")
                    self.assertEqual(first.count, 2)
                    self.assertEqual(second.count, 2)
                    self.assertEqual(len(first.items), 1)
                    self.assertNotEqual(first.items[0].id, second.items[0].id)
                    by_symbol = await list_assets(db, user, page=1, page_size=20, search="hwm")
                    self.assertEqual([a.symbol for a in by_symbol.items], ["HWM"])
                    literal = await list_assets(db, user, page=1, page_size=20, search="%_")
                    self.assertEqual([a.symbol for a in literal.items], ["TEST"])
                    empty = await list_assets(db, user, page=1, page_size=20, search="missing")
                    self.assertEqual(empty.count, 0)
                    self.assertEqual(empty.items, [])
                    all_assets = await list_assets(db, user, page=1, page_size=20, search="   ")
                    self.assertEqual(all_assets.count, 4)
        finally:
            await engine.dispose()
