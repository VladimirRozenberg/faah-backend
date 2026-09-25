import unittest
from datetime import datetime

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db import Base, get_db
from models import (
    Asset,
    ClassificationAsset,
    ClassificationNiche,
    DataSource,
    Niche,
    Prompt,
    SourceClassification,
)
from routers.data_sources import router


class DataSourceFilterTests(unittest.IsolatedAsyncioTestCase):
    async def test_filters_are_composable_and_count_is_filtered(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        tables = [
            model.__table__
            for model in (
                Asset,
                Niche,
                Prompt,
                DataSource,
                SourceClassification,
                ClassificationAsset,
                ClassificationNiche,
            )
        ]
        try:
            async with engine.begin() as connection:
                await connection.run_sync(
                    lambda sync_connection: Base.metadata.create_all(
                        sync_connection,
                        tables=tables,
                    )
                )

            session_factory = async_sessionmaker(engine, expire_on_commit=False)
            async with session_factory() as db:
                prompt = Prompt(
                    prm_name="classification",
                    prm_type="test",
                    prm_prompt_text="test",
                )
                nvda = Asset(ast_symbol="NVDA", ast_name="Nvidia", ast_type="stock")
                apple = Asset(ast_symbol="AAPL", ast_name="Apple", ast_type="stock")
                ai = Niche(
                    nic_name="Artificial Intelligence",
                    nic_category="technology",
                    nic_description="AI businesses",
                )
                technology = DataSource(
                    src_type="rss:Technology",
                    src_title="Nvidia launches a new AI chip",
                    src_content="Datacenter demand remains strong.",
                    src_original_url="https://example.com/nvidia-chip",
                    src_published_at=datetime(2026, 9, 20, 10),
                    src_created_at=datetime(2026, 9, 20, 11),
                    src_is_processed=True,
                )
                markets = DataSource(
                    src_type="rss:Markets",
                    src_title="Apple market update",
                    src_content="A routine market summary.",
                    src_original_url="https://example.com/apple",
                    src_published_at=datetime(2026, 9, 21, 10),
                    src_created_at=datetime(2026, 9, 21, 11),
                    src_is_processed=True,
                )
                pending = DataSource(
                    src_type="manual",
                    src_title="Unprocessed source",
                    src_created_at=datetime(2026, 9, 22, 11),
                    src_is_processed=False,
                )
                db.add_all(
                    [prompt, nvda, apple, ai, technology, markets, pending]
                )
                await db.flush()

                tech_classification = SourceClassification(
                    cls_src_id=technology.src_id,
                    cls_prm_id=prompt.prm_id,
                    cls_category="technology",
                    cls_importance="high",
                    cls_sentiment="positive",
                    cls_should_trigger=True,
                )
                market_classification = SourceClassification(
                    cls_src_id=markets.src_id,
                    cls_prm_id=prompt.prm_id,
                    cls_category="finance",
                    cls_importance="low",
                    cls_sentiment="neutral",
                    cls_should_trigger=False,
                )
                db.add_all([tech_classification, market_classification])
                await db.flush()
                db.add_all(
                    [
                        ClassificationAsset(
                            cla_cls_id=tech_classification.cls_id,
                            cla_ast_id=nvda.ast_id,
                        ),
                        ClassificationAsset(
                            cla_cls_id=market_classification.cls_id,
                            cla_ast_id=apple.ast_id,
                        ),
                        ClassificationNiche(
                            cln_cls_id=tech_classification.cls_id,
                            cln_nic_id=ai.nic_id,
                        ),
                    ]
                )
                await db.commit()

                app = FastAPI()
                app.include_router(router)

                async def test_db():
                    yield db

                app.dependency_overrides[get_db] = test_db
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.get(
                        "/api/data-sources",
                        params={
                            "q": "nvidia",
                            "source_type": "RSS:TECHNOLOGY",
                            "asset_symbol": "nvda",
                            "niche": "artificial intelligence",
                            "category": "TECHNOLOGY",
                            "importance": "high",
                            "sentiment": "positive",
                            "should_trigger": "true",
                            "is_processed": "true",
                        },
                    )

                    self.assertEqual(response.status_code, 200)
                    body = response.json()
                    self.assertEqual(body["count"], 1)
                    self.assertEqual(len(body["items"]), 1)
                    self.assertEqual(body["items"][0]["src_id"], technology.src_id)
                    self.assertEqual(body["items"][0]["related_assets"], ["NVDA"])

                    response = await client.get(
                        "/api/data-sources",
                        params={
                            "published_from": "2026-09-20T12:00:00Z",
                            "published_to": "2026-09-22T00:00:00Z",
                            "sort_by": "published_at",
                            "sort_order": "asc",
                        },
                    )
                    body = response.json()
                    self.assertEqual(body["count"], 1)
                    self.assertEqual(body["items"][0]["src_id"], markets.src_id)

                    response = await client.get(
                        "/api/data-sources",
                        params={"is_processed": "false"},
                    )
                    self.assertEqual(response.json()["count"], 1)
                    self.assertEqual(response.json()["items"][0]["src_id"], pending.src_id)
        finally:
            await engine.dispose()

    async def test_rejects_reversed_date_range(self):
        app = FastAPI()
        app.include_router(router)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get(
                "/api/data-sources",
                params={
                    "created_from": "2026-09-22T00:00:00Z",
                    "created_to": "2026-09-20T00:00:00Z",
                },
            )

        self.assertEqual(response.status_code, 422)
        self.assertIn("created_from", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
