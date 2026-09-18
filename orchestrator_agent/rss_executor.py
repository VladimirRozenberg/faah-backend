"""Generic RSS executor owned by the orchestrator runtime."""

from __future__ import annotations

import asyncio
import logging

from ingestion.rss import ingest_rss_feed
from orchestrator_agent.rss_repository import RSSFeedRepository


logger = logging.getLogger(__name__)


class RSSFeedExecutor:
    def __init__(self, repository: RSSFeedRepository):
        self.repository = repository

    async def run_due(self) -> int:
        """Run every feed currently due and return the number of executions."""

        executions = 0
        while claim := await self.repository.claim_next_due():
            executions += 1
            run_id = claim.run.rfr_id
            feed_id = claim.feed.rsf_id
            feed_name = claim.feed.rsf_name
            try:
                source_ids = await ingest_rss_feed(
                    self.repository.session,
                    feed_name=claim.feed.rsf_name,
                    feed_url=claim.feed.rsf_url,
                    source_prefix=claim.feed.rsf_source_prefix,
                )
                await self.repository.complete_run(
                    run_id=run_id,
                    feed_id=feed_id,
                    items_processed=len(source_ids),
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self.repository.session.rollback()
                await self.repository.fail_run(
                    run_id=run_id,
                    feed_id=feed_id,
                    error=str(exc),
                )
                logger.exception("RSS feed execution failed: %s", feed_name)

        return executions
