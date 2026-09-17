from fastapi import FastAPI
from sqlalchemy import text, select
import os

from routers import (
    analyses,
    assets,
    classifications,
    data_sources,
    health,
    live_market,
    portfolios,
    signals,
    favorites,
)
import prompt.prompts as prompts
from prompt.classification import classify_source
from db import DbSession
from ingestion import rss
from models import DataSource
from workers import workers
from extraction.extract_article import extract_article
from auth import login
from admin import gestion
import logging
from dotenv import load_dotenv
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from config.rss_feeds import RSS_FEEDS
from ingestion.rss import ingest_rss_feed
from workers.workers import poll_rss_worker

load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# Uvicorn configures its own named loggers before importing this module. Set
# the root level explicitly so FAAH module logs are not left at WARNING.
logging.getLogger().setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

logger = logging.getLogger(__name__)


RUN_WORKERS = os.getenv("RUN_WORKERS", "false").lower() == "true"


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker_tasks: list[asyncio.Task] = []

    if RUN_WORKERS:
        worker_tasks = [
            asyncio.create_task(
                poll_rss_worker(feed),
                name=f"poll-rss-{feed.name}",
            )
            for feed in RSS_FEEDS
        ]

        logger.info(
            "Started %d RSS worker(s): %s",
            len(worker_tasks),
            ", ".join(feed.name for feed in RSS_FEEDS),
        )
    else:
        logger.info("Background workers are disabled")

    app.state.worker_tasks = worker_tasks

    try:
        yield
    finally:
        logger.info(
            "Stopping %d background worker(s)",
            len(worker_tasks),
        )

        for task in worker_tasks:
            task.cancel()

        results = await asyncio.gather(
            *worker_tasks,
            return_exceptions=True,
        )

        for task, result in zip(worker_tasks, results):
            if isinstance(result, Exception) and not isinstance(
                result,
                asyncio.CancelledError,
            ):
                logger.error(
                    "Worker %s stopped with an error: %r",
                    task.get_name(),
                    result,
                )

        logger.info("All background workers stopped")


# Keep documentation disabled unless a private path is configured.
DOCS_PATH = os.getenv("DOCS_PATH", "").strip().rstrip("/") or None
if DOCS_PATH and (
    not DOCS_PATH.startswith("/")
    or DOCS_PATH in {"/docs", "/redoc", "/openapi.json"}
    or any(char in DOCS_PATH for char in "?#{}")
):
    raise ValueError("DOCS_PATH must be a non-default absolute URL path")

app = FastAPI(
    title="FAAH API",
    description="API backend de l'application FAAH",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=DOCS_PATH,
    redoc_url=None,
    openapi_url=f"{DOCS_PATH}/openapi.json" if DOCS_PATH else None,
    swagger_ui_oauth2_redirect_url=None,
)

app.include_router(health.router)
app.include_router(assets.router)
app.include_router(live_market.router)
app.include_router(portfolios.router)
app.include_router(data_sources.router)
app.include_router(classifications.router)
app.include_router(analyses.router)
app.include_router(signals.router)
app.include_router(prompts.router, prefix="/prompt")
app.include_router(workers.router)
app.include_router(login.router)
app.include_router(gestion.router)
app.include_router(favorites.router)
 


@app.get("/test-db")
async def test_db(db: DbSession):
    result = await db.execute(text("SELECT * FROM test"))
    rows = result.mappings().all()

    return {
        "connected": True,
        "rows": [dict(row) for row in rows],
    }



RSS_URL = "https://www.investing.com/rss/news_25.rss"



@app.get("/ingest-rss")
async def ingest_rss(db: DbSession):
    feed = RSS_FEEDS[0]
    news = await ingest_rss_feed(
        db,
        feed_name=feed.name,
        feed_url=feed.url,
        source_prefix=feed.source_prefix,
        classify_articles=False,
    )

    if not news:
        return {
            "message": "No new articles found."
        }

    result = await db.execute(
        select(DataSource)
        .where(DataSource.src_id.in_(news))
        .order_by(
            DataSource.src_created_at.desc(),
            DataSource.src_id.desc(),
        )
    )

    new_sources = result.scalars().all()

    return {
        "new_count": len(new_sources),

        "articles": [
            {
                "id": source.src_id,
                "title": source.src_title,
                "url": source.src_original_url,
                "content": source.src_content,
                "published_at": source.src_published_at,
            }
            for source in new_sources
        ]
    }


@app.get("/test-rss-analysis")
async def test_rss_analysis(db: DbSession):

    news = await rss.ingest_investing_stock_news(db)

    if not news:
        return {
            "message": "No new articles found."
        }

    results = []

    for source_id in news:

        classification, analysis = await classify_source(
            source_id,
            db,
        )

        results.append(
            {
                "source_id": source_id,
                "category": classification.cls_category,
                "importance": classification.cls_importance,
                "sentiment": classification.cls_sentiment,
                "should_trigger": classification.cls_should_trigger,
                "reason": classification.cls_reason,
                "analysis": (
                    {
                        "summary": analysis.anl_summary,
                        "direction": analysis.anl_direction,
                        "market_sentiment": analysis.anl_market_sentiment,
                        "confidence": analysis.anl_confidence,
                        "risk": analysis.anl_risk_level,
                        "timeframe": analysis.anl_timeframe,
                    }
                    if classification.cls_should_trigger
                    else None
                ),
            }
        )

    return {
        "processed": len(results),
        "results": results,
    }

@app.get("/test_article_extraction")
async def test_article_extraction(url : str):
    article_content = await extract_article(url)

    if article_content is None:
        return {
            "message": "Failed to extract article content."
            }
    return article_content
"""
SOURCES : https://fastapi.tiangolo.com/ --DOCUMENTATION FASTAPI
        https://docs.docker.com/compose/intro/features-uses/ --DOCUMENTATION DOCKER COMPOSE
"""
