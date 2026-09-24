"""Vérifie les vrais liens SQL sur une base temporaire, sans API externe."""
import unittest
from datetime import datetime

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db import Base, get_db
from models import Asset, ClassificationAsset, DataSource, Prompt, SourceClassification
from routers.assets import router


class AssetNewsTests(unittest.IsolatedAsyncioTestCase):
    async def test_news_follow_database_links_not_text(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        tables = [m.__table__ for m in [Asset, Prompt, DataSource, SourceClassification, ClassificationAsset]]
        try:
            async with engine.begin() as connection:
                await connection.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                hwm = Asset(ast_symbol="HWM", ast_name="Howmet Aerospace Inc.", ast_type="stock")
                other = Asset(ast_symbol="AAPL", ast_name="Apple", ast_type="stock")
                empty = Asset(ast_symbol="EMPTY", ast_name="Sans actualité", ast_type="stock")
                prompt = Prompt(prm_name="test", prm_type="test", prm_prompt_text="test")
                # Aucun nom d'actif dans l'article lié ; une mention dans l'article non lié.
                linked = DataSource(src_type="news", src_title="Évolution du secteur", src_created_at=datetime(2026, 9, 20))
                newer = DataSource(src_type="news", src_title="Nouvelle commande", src_created_at=datetime(2026, 9, 21))
                unrelated = DataSource(src_type="news", src_title="HWM Howmet Aerospace Inc.")
                db.add_all([hwm, other, empty, prompt, linked, newer, unrelated])
                await db.flush()
                for source, asset in [(linked, hwm), (linked, hwm), (newer, hwm), (unrelated, other)]:
                    classification = SourceClassification(cls_src_id=source.src_id, cls_prm_id=prompt.prm_id, cls_should_trigger=True)
                    db.add(classification)
                    await db.flush()
                    db.add(ClassificationAsset(cla_cls_id=classification.cls_id, cla_ast_id=asset.ast_id))
                await db.commit()

                app = FastAPI()
                app.include_router(router)
                async def test_db():
                    yield db
                app.dependency_overrides[get_db] = test_db
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    response = await client.get("/api/assets/hwm/news")
                    self.assertEqual(response.status_code, 200)
                    body = response.json()
                    self.assertEqual(body["count"], 2)
                    self.assertEqual([n["src_id"] for n in body["items"]], [newer.src_id, linked.src_id])
                    # Autre actif : uniquement ses propres associations.
                    response = await client.get("/api/assets/AAPL/news")
                    self.assertEqual([n["src_id"] for n in response.json()["items"]], [unrelated.src_id])
                    response = await client.get("/api/assets/EMPTY/news")
                    self.assertEqual(response.json(), {"count": 0, "items": []})
                    response = await client.get("/api/assets/UNKNOWN/news")
                    self.assertEqual(response.status_code, 404)
        finally:
            await engine.dispose()
