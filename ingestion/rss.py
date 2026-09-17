from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
import asyncio
import feedparser
from ingestion.feed_http import fetch_feed_content
from sqlalchemy import and_, or_, select

from db import DbSession
from models import Analysis, DataSource, SourceClassification

from prompt.classification import classify_source

logger = logging.getLogger(__name__)

RETRY_WINDOW = timedelta(hours=2)


# Start with one high-value feed.
# Add more Investing.com feeds later without changing the ingestion logic.




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
    content = await fetch_feed_content(feed_url)
    feed = feedparser.parse(content)

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
    classify_articles: bool = True,
) -> list[int]:
    """
    Fetch an RSS feed and insert new articles.

    When requested, also classify every unprocessed article found in the
    current feed. Workers keep this enabled; ingestion-only test routes can
    disable it.
    """
    entries = await fetch_rss(feed_url)

    source_type = f"{source_prefix}:{feed_name}"
    retry_cutoff = (
        datetime.now(timezone.utc) - RETRY_WINDOW
    ).replace(tzinfo=None)

    # Retry recent unfinished work even when an article has already rolled out
    # of the feed response. Existing classifications are resumed rather than
    # duplicated by classify_source.
    retry_result = await db.scalars(
        select(DataSource)
        .outerjoin(
            SourceClassification,
            SourceClassification.cls_src_id == DataSource.src_id,
        )
        .outerjoin(
            Analysis,
            Analysis.anl_cls_id == SourceClassification.cls_id,
        )
        .where(
            DataSource.src_type == source_type,
            or_(
                DataSource.src_published_at >= retry_cutoff,
                and_(
                    DataSource.src_published_at.is_(None),
                    DataSource.src_created_at >= retry_cutoff,
                ),
            ),
            or_(
                DataSource.src_is_processed.is_(False),
                and_(
                    SourceClassification.cls_should_trigger.is_(True),
                    Analysis.anl_id.is_(None),
                ),
            ),
        )
        .distinct()
        .order_by(DataSource.src_created_at)
    )
    source_ids_to_classify = [
        source.src_id for source in retry_result.all()
    ]

    if not entries:
        entries = []

    urls = {entry["url"] for entry in entries}

    result = await db.execute(
        select(DataSource).where(
            DataSource.src_original_url.in_(urls)
        )
    )

    existing_sources = {
        source.src_original_url: source
        for source in result.scalars().all()
    }

    new_sources: list[DataSource] = []

    if not classify_articles:
        source_ids_to_classify = []

    for entry in entries:
        if entry["url"] in existing_sources:
            continue

        source = DataSource(
            src_type=source_type,
            src_title=entry["title"],
            src_original_url=entry["url"],
            src_content=entry["content"],
            src_published_at=entry["published_at"],
            src_is_processed=False,
        )

        db.add(source)
        new_sources.append(source)

        # Prevent duplicates within the same response.
        existing_sources[entry["url"]] = source

    new_source_ids: list[int] = []

    if new_sources:
        await db.flush()

        new_source_ids = [
            source.src_id
            for source in new_sources
        ]

        if classify_articles:
            source_ids_to_classify.extend(new_source_ids)

        # Save articles before classification.
        await db.commit()

        logger.info(
            "RSS feed %s: inserted %d new article(s)",
            feed_name,
            len(new_source_ids),
        )

    # dict.fromkeys removes duplicate IDs while preserving order.
    for source_id in dict.fromkeys(source_ids_to_classify):
        try:
            logger.info(
                "Classifying RSS source %d from %s",
                source_id,
                feed_name,
            )

            await classify_source(source_id, db)

            # Harmless if classify_source already commits.
            await db.commit()

        except asyncio.CancelledError:
            raise

        except Exception:
            # Reset the SQLAlchemy session so later articles can continue.
            await db.rollback()

            logger.exception(
                "Classification failed for source %d; "
                "it will be retried during the next %s poll",
                source_id,
                feed_name,
            )

    return new_source_ids
