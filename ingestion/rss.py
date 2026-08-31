from __future__ import annotations

import html
import logging
import re
from datetime import datetime
from typing import Any

import feedparser
import httpx
from sqlalchemy import select

from db import DbSession
from models import DataSource

from prompt.prompt_text import classify_source

logger = logging.getLogger(__name__)


# Start with one high-value feed.
# Add more Investing.com feeds later without changing the ingestion logic.
INVESTING_RSS_FEEDS = {
    "stock_market": "https://www.investing.com/rss/news_25.rss",
    "tech_stocks": "https://news.google.com/rss/search?q=technology+stocks&hl=en-US&gl=US&ceid=US:en"
}


REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
}


def _clean_text(value: str | None) -> str:
    """
    RSS descriptions can contain small amounts of HTML.
    Keep V1 simple: remove tags, decode entities, normalize whitespace.
    """
    if not value:
        return ""

    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return " ".join(value.split())


def _parse_published_at(entry: Any) -> datetime | None:
    """
    feedparser exposes published_parsed / updated_parsed as struct_time.
    The current DB schema uses TIMESTAMP without timezone, so return a
    naive datetime representing the feed timestamp.
    """
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")

    if not parsed:
        return None

    return datetime(
        parsed.tm_year,
        parsed.tm_mon,
        parsed.tm_mday,
        parsed.tm_hour,
        parsed.tm_min,
        parsed.tm_sec,
    )


async def fetch_rss(feed_url: str) -> list[dict]:
    """
    Fetch one RSS endpoint and normalize its entries.

    This function does not touch the database and does not invoke an LLM.
    """
    async with httpx.AsyncClient(
        headers=REQUEST_HEADERS,
        follow_redirects=True,
        timeout=20.0,
    ) as client:
        response = await client.get(feed_url)
        response.raise_for_status()

    feed = feedparser.parse(response.content)

    # feedparser can recover from some malformed XML. Only fail when
    # parsing failed and there are no usable entries.
    if feed.bozo and not feed.entries:
        raise ValueError(
            f"Could not parse RSS feed: {feed.bozo_exception}"
        )

    entries: list[dict] = []

    for entry in feed.entries:
        url = entry.get("link")

        if not url:
            continue

        entries.append(
            {
                "title": _clean_text(entry.get("title")),
                "url": url.strip(),
                "content": _clean_text(
                    entry.get("summary")
                    or entry.get("description")
                    or ""
                ),
                "published_at": _parse_published_at(entry),
            }
        )

    return entries


async def ingest_rss_feed(
    db: DbSession,
    *,
    feed_name: str,
    feed_url: str,
    source_prefix: str,
) -> list[int]:
    """
    Fetch one RSS feed, insert unseen articles into data_sources,
    and return the IDs of newly inserted rows.
    Deduplication is performed using src_original_url.
    """
    entries = await fetch_rss(feed_url)

    if not entries:
        return []

    urls = {entry["url"] for entry in entries}

    result = await db.execute(
        select(DataSource.src_original_url).where(
            DataSource.src_original_url.in_(urls)
        )
    )

    existing_urls = set(result.scalars().all())

    new_sources: list[DataSource] = []

    for entry in entries:
        if entry["url"] in existing_urls:
            continue

        source = DataSource(
            src_type=f"{source_prefix}:{feed_name}",
            src_title=entry["title"],
            src_original_url=entry["url"],
            src_content=entry["content"],
            src_published_at=entry["published_at"],
            src_is_processed=False,
        )

        db.add(source)
        new_sources.append(source)

        # Protect against duplicate URLs appearing twice inside one feed response.
        existing_urls.add(entry["url"])

    if not new_sources:
        return []

    # Generate src_id values before commit.
    await db.flush()

    new_source_ids = [source.src_id for source in new_sources]

    await db.commit()

    logger.info(
        "RSS feed %s: inserted %d new article(s)",
        feed_name,
        len(new_source_ids),
    )

    return new_source_ids


async def ingest_investing_stock_news(db: DbSession) -> list[int]:
    """
    Fetch Investing.com's Stock Market News RSS feed once.
    """
    source_ids = await ingest_rss_feed(
        db,
        feed_name="stock_market",
        feed_url=INVESTING_RSS_FEEDS["stock_market"],
        source_prefix="rss:investing",
    )
    for source_id in source_ids:
        logger.info("New Investing.com article: %d", source_id)
        await classify_source(source_id, db)
    return source_ids




async def ingest_tech_stock_news(db: DbSession) -> list[int]:
    """
    Fetch Investing.com's Stock Market News RSS feed once.
    """
    source_ids = await ingest_rss_feed(
        db,
        feed_name="tech_stocks",
        feed_url=INVESTING_RSS_FEEDS["tech_stocks"],
        source_prefix="rss:investing",
    )
    for source_id in source_ids:
        logger.info("New Investing.com article: %d", source_id)
        await classify_source(source_id, db)
    return source_ids


async def ingest_all_investing_feeds(db: DbSession) -> list[int]:
    """
    Fetch every Investing.com feed configured in INVESTING_RSS_FEEDS.

    For now this is only Stock Market News. Later you can add:
        "company_news": "https://www.investing.com/rss/news_356.rss",
        "earnings": "https://www.investing.com/rss/news_1062.rss",
        "analyst_ratings": "https://www.investing.com/rss/news_1061.rss",
        "economic_indicators": "https://www.investing.com/rss/news_95.rss",
    """
    new_source_ids: list[int] = []

    for feed_name, feed_url in INVESTING_RSS_FEEDS.items():
        ids = await ingest_rss_feed(
            db,
            feed_name=feed_name,
            feed_url=feed_url,
            source_prefix="rss:investing",
        )
        new_source_ids.extend(ids)

    return new_source_ids

