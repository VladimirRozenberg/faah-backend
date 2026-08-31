import asyncio
import feedparser
from sqlalchemy import select, text
import logging
from fastapi import APIRouter

from ingestion import rss
from models import DataSource

from db import DbSession

router = APIRouter(tags=["Workers"])



logger = logging.getLogger(__name__)

POLL_INTERVAL = 360  # 5 mins

@router.get("/poll-rss")
async def poll_rss(db: DbSession):
    """
    Poll the RSS feed for new articles and ingest them into the database.
    This endpoint is intended to be called by a scheduler or cron job.
    """
    while True:
        try:
            news = await rss.ingest_investing_stock_news(db)

            if news:
                logger.info(f"Ingested {len(news)} new articles.")
            else:
                logger.info("No new articles found.")

        except Exception as e:
            logger.error(f"Error while polling RSS feed: {e}")
            return {"error": str(e)}

        await asyncio.sleep(POLL_INTERVAL)


@router.get("/poll-rss_tech")
async def poll_rss_tech(db: DbSession):
    """
    Poll the RSS feed for new articles and ingest them into the database.
    This endpoint is intended to be called by a scheduler or cron job.
    """
    while True:
        try:
            news = await rss.ingest_tech_stock_news(db)

            if news:
                logger.info(f"Ingested {len(news)} new articles.")
            else:
                logger.info("No new articles found.")

        except Exception as e:
            logger.error(f"Error while polling RSS feed: {e}")
            return {"error": str(e)}

        await asyncio.sleep(POLL_INTERVAL)