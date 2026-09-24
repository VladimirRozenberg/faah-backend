"""Minute-level opportunity detector and portfolio strategist runtime."""

from __future__ import annotations

import asyncio
import logging
import os

from sqlalchemy import select

from db import AsyncSessionLocal
from live_market.redis_client import (
    get_latest_quote,
    get_opportunity_sample,
    save_opportunity_sample,
)
from models import Asset
from orchestrator_agent.follow_up import (
    FollowUpAnalysisExecutor,
    FollowUpAnalysisRepository,
)
from portfolio_strategist.detector import detect_price_movement
from portfolio_strategist.executors import (
    StrategistReviewExecutor,
    MarketEventAnalysisExecutor,
)
from portfolio_strategist.repository import StrategistRepository


logger = logging.getLogger(__name__)
SCAN_SECONDS = 60


def configured_threshold_pct() -> float:
    try:
        value = float(os.getenv("OPPORTUNITY_PRICE_MOVE_PCT", "2.0"))
    except ValueError:
        return 2.0
    return value if value > 0 else 2.0


async def scan_tracked_prices(repository: StrategistRepository) -> int:
    """Compare the latest quote with the preceding minute-level sample."""

    assets = list(
        (
            await repository.session.scalars(
                select(Asset)
                .where(Asset.ast_is_tracked.is_(True))
                .order_by(Asset.ast_id)
            )
        ).all()
    )
    detected = 0
    threshold = configured_threshold_pct()
    for asset in assets:
        try:
            current = await get_latest_quote(asset.ast_symbol)
            if current is None:
                continue
            previous = await get_opportunity_sample(asset.ast_symbol)
            movement = detect_price_movement(
                previous,
                current,
                threshold_pct=threshold,
            )
            if previous is None or current.timestamp > previous.timestamp:
                await save_opportunity_sample(current)
            if movement is not None:
                event = await repository.create_price_event(asset, movement)
                detected += int(event is not None)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Opportunity scan failed for %s", asset.ast_symbol)
            await repository.session.rollback()
    return detected


async def run_strategist_service() -> None:
    """Detect opportunities, research price events and run due strategists."""

    logger.info("Portfolio strategist service started")
    try:
        while True:
            async with AsyncSessionLocal() as db:
                created = await StrategistRepository(db).ensure_strategists()
                if created:
                    logger.info("Created %d portfolio strategist(s)", created)

            async with AsyncSessionLocal() as db:
                detected = await scan_tracked_prices(StrategistRepository(db))
                if detected:
                    logger.info("Detected %d material price movement(s)", detected)

            async with AsyncSessionLocal() as db:
                queued = await StrategistRepository(db).dispatch_new_signals()
                if queued:
                    logger.info("Queued %d signal-triggered strategist check(s)", queued)

            async with AsyncSessionLocal() as db:
                analyzed = await MarketEventAnalysisExecutor(
                    StrategistRepository(db)
                ).run_pending()
                if analyzed:
                    logger.info("Processed %d market-event analysis job(s)", analyzed)

            async with AsyncSessionLocal() as db:
                queued = await StrategistRepository(db).dispatch_analyzed_events()
                if queued:
                    logger.info("Queued %d price-triggered strategist check(s)", queued)

            async with AsyncSessionLocal() as db:
                full_reviews = await StrategistRepository(db).queue_due_full_reviews()
                if full_reviews:
                    logger.info("Queued %d full portfolio review(s)", full_reviews)

            async with AsyncSessionLocal() as db:
                follow_ups = await FollowUpAnalysisExecutor(
                    FollowUpAnalysisRepository(db)
                ).run_pending()
                if follow_ups:
                    logger.info("Processed %d strategist follow-up analysis job(s)", follow_ups)

            async with AsyncSessionLocal() as db:
                reviewed = await StrategistReviewExecutor(
                    StrategistRepository(db)
                ).run_pending()
                if reviewed:
                    logger.info("Processed %d strategist review(s)", reviewed)

            await asyncio.sleep(SCAN_SECONDS)
    finally:
        logger.info("Portfolio strategist service stopped")
