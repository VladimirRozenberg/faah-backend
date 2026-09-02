import asyncio
import feedparser
from sqlalchemy import select, text
import logging
from fastapi import APIRouter

from ingestion import rss
from models import DataSource
from config.rss_feeds import RSS_FEEDS, RSSFeed
from db import DbSession, AsyncSessionLocal

router = APIRouter(tags=["Workers"])



logger = logging.getLogger(__name__)

POLL_INTERVAL = 360  # 5 mins

async def poll_rss_worker(feed: RSSFeed) -> None:
    logger.info("RSS worker started: %s", feed.name)

    try:
        while True:
            try:
                async with AsyncSessionLocal() as db:
                    new_source_ids = await rss.ingest_rss_feed(
                        db,
                        feed_name=feed.name,
                        feed_url=feed.url,
                        source_prefix=feed.source_prefix,
                    )

                    logger.info(
                        "[%s] Ingested %d new article(s)",
                        feed.name,
                        len(new_source_ids),
                    )

            except Exception:
                logger.exception(
                    "[%s] RSS worker failed",
                    feed.name,
                )

            await asyncio.sleep(feed.poll_interval)

    finally:
        logger.info("RSS worker stopped: %s", feed.name)