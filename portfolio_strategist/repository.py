"""PostgreSQL state and queues for opportunities and portfolio strategists."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    Analysis,
    Asset,
    AssetNiche,
    MarketOpportunityEvent,
    Portfolio,
    PortfolioAsset,
    PortfolioStrategist,
    PortfolioStrategistRun,
    Signal,
)
from portfolio_strategist.detector import risk_is_compatible
from portfolio_strategist.schemas import PriceMovement


FULL_REVIEW_INTERVAL = timedelta(hours=2)
EVENT_COOLDOWN = timedelta(minutes=15)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StrategistRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def ensure_strategists(self) -> int:
        """Create one strategist per active portfolio and track held assets."""

        portfolio_ids = set(
            (
                await self.session.scalars(
                    select(Portfolio.prt_id).where(Portfolio.prt_is_active.is_(True))
                )
            ).all()
        )
        existing = set(
            (
                await self.session.scalars(
                    select(PortfolioStrategist.pst_prt_id).where(
                        PortfolioStrategist.pst_prt_id.in_(portfolio_ids)
                    )
                )
            ).all()
        ) if portfolio_ids else set()

        for portfolio_id in sorted(portfolio_ids - existing):
            self.session.add(PortfolioStrategist(pst_prt_id=portfolio_id))

        held_asset_ids = select(PortfolioAsset.pas_ast_id).where(
            PortfolioAsset.pas_is_active.is_(True)
        )
        await self.session.execute(
            update(Asset)
            .where(
                Asset.ast_id.in_(held_asset_ids),
                Asset.ast_is_tracked.is_(False),
            )
            .values(ast_is_tracked=True, ast_updated_at=utc_now())
        )
        await self.session.commit()
        return len(portfolio_ids - existing)

    async def create_price_event(
        self,
        asset: Asset,
        movement: PriceMovement,
    ) -> MarketOpportunityEvent | None:
        """Persist a movement unless the same direction is cooling down."""

        recent = await self.session.scalar(
            select(MarketOpportunityEvent.moe_id)
            .where(
                MarketOpportunityEvent.moe_ast_id == asset.ast_id,
                MarketOpportunityEvent.moe_event_type == movement.event_type,
                MarketOpportunityEvent.moe_detected_at
                >= movement.detected_at - EVENT_COOLDOWN,
            )
            .limit(1)
        )
        if recent is not None:
            return None

        direction = "increased" if movement.change_pct > 0 else "decreased"
        reason = (
            f"{asset.ast_symbol} ({asset.ast_name}) {direction} by "
            f"{abs(movement.change_pct):.2f}% over {movement.window_seconds} seconds, "
            f"from {movement.price_before:.4f} to {movement.price_after:.4f}. "
            "Research current news and market developments that could explain the "
            "movement, distinguish confirmed causes from speculation, and assess "
            "whether the implications appear temporary or structural."
        )
        event = MarketOpportunityEvent(
            moe_ast_id=asset.ast_id,
            moe_event_type=movement.event_type,
            moe_price_before=Decimal(str(movement.price_before)),
            moe_price_after=Decimal(str(movement.price_after)),
            moe_change_pct=Decimal(str(movement.change_pct)),
            moe_window_seconds=movement.window_seconds,
            moe_reason=reason,
            moe_status="detected",
            moe_detected_at=movement.detected_at,
        )
        self.session.add(event)
        await self.session.commit()
        await self.session.refresh(event)
        return event

    async def dispatch_new_signals(self) -> int:
        """Queue short checks for held assets and compatible niche opportunities."""

        strategists = list(
            (
                await self.session.scalars(
                    select(PortfolioStrategist)
                    .join(Portfolio, Portfolio.prt_id == PortfolioStrategist.pst_prt_id)
                    .where(
                        PortfolioStrategist.pst_status == "active",
                        Portfolio.prt_is_active.is_(True),
                    )
                    .order_by(PortfolioStrategist.pst_id)
                )
            ).all()
        )
        maximum_signal_id = await self.session.scalar(select(func.max(Signal.sig_id)))
        if maximum_signal_id is None:
            return 0

        queued = 0
        now = utc_now()
        naive_now = now.replace(tzinfo=None)
        recent_cutoff = naive_now - timedelta(hours=24)

        for strategist in strategists:
            portfolio = await self.session.get(Portfolio, strategist.pst_prt_id)
            if portfolio is None:
                continue
            owned_ids = set(
                (
                    await self.session.scalars(
                        select(PortfolioAsset.pas_ast_id).where(
                            PortfolioAsset.pas_prt_id == strategist.pst_prt_id,
                            PortfolioAsset.pas_is_active.is_(True),
                        )
                    )
                ).all()
            )
            owned_niches = set()
            if owned_ids:
                owned_niches = set(
                    (
                        await self.session.scalars(
                            select(AssetNiche.ani_nic_id).where(
                                AssetNiche.ani_ast_id.in_(owned_ids)
                            )
                        )
                    ).all()
                )

            rows = (
                await self.session.execute(
                    select(Signal, Analysis, Asset)
                    .join(Analysis, Analysis.anl_id == Signal.sig_anl_id)
                    .join(Asset, Asset.ast_id == Signal.sig_ast_id)
                    .where(
                        Signal.sig_id > strategist.pst_last_signal_id,
                        Signal.sig_status == "active",
                        Signal.sig_created_at >= recent_cutoff,
                        or_(
                            Signal.sig_expires_at.is_(None),
                            Signal.sig_expires_at > naive_now,
                        ),
                        or_(
                            Signal.sig_prt_id.is_(None),
                            Signal.sig_prt_id == strategist.pst_prt_id,
                        ),
                    )
                    .order_by(Signal.sig_id)
                )
            ).all()
            candidate_ids = {signal.sig_ast_id for signal, _, _ in rows}
            candidate_niches: dict[int, set[int]] = {}
            if candidate_ids:
                niche_rows = (
                    await self.session.execute(
                        select(AssetNiche.ani_ast_id, AssetNiche.ani_nic_id).where(
                            AssetNiche.ani_ast_id.in_(candidate_ids)
                        )
                    )
                ).all()
                for asset_id, niche_id in niche_rows:
                    candidate_niches.setdefault(asset_id, set()).add(niche_id)

            existing_signal_ids = set(
                (
                    await self.session.scalars(
                        select(PortfolioStrategistRun.psr_sig_id).where(
                            PortfolioStrategistRun.psr_pst_id == strategist.pst_id,
                            PortfolioStrategistRun.psr_sig_id.is_not(None),
                        )
                    )
                ).all()
            )
            for signal, analysis, asset in rows:
                owned = asset.ast_id in owned_ids
                same_niche = bool(
                    owned_niches.intersection(candidate_niches.get(asset.ast_id, set()))
                )
                compatible_opportunity = (
                    not owned
                    and signal.sig_action == "buy"
                    and same_niche
                    and risk_is_compatible(
                        portfolio.prt_risk_tolerance,
                        analysis.anl_risk_level,
                    )
                )
                if not owned and not compatible_opportunity:
                    continue
                if signal.sig_id in existing_signal_ids:
                    continue

                scope = "held asset" if owned else "compatible niche opportunity"
                self.session.add(
                    PortfolioStrategistRun(
                        psr_pst_id=strategist.pst_id,
                        psr_ast_id=asset.ast_id,
                        psr_sig_id=signal.sig_id,
                        psr_review_type="targeted_signal",
                        psr_status="pending",
                        psr_priority=(
                            5 if owned and signal.sig_action == "sell" else 4
                        ),
                        psr_reason=(
                            f"New {signal.sig_action} signal for {asset.ast_symbol} "
                            f"({scope}); confidence={signal.sig_confidence}."
                        ),
                    )
                )
                queued += 1

            strategist.pst_last_signal_id = maximum_signal_id
            strategist.pst_updated_at = now

        await self.session.commit()
        return queued

    async def dispatch_analyzed_events(self) -> int:
        """Wake strategists that own the asset after shared analysis succeeds."""

        events = list(
            (
                await self.session.scalars(
                    select(MarketOpportunityEvent)
                    .where(MarketOpportunityEvent.moe_status == "analyzed")
                    .order_by(MarketOpportunityEvent.moe_detected_at)
                )
            ).all()
        )
        queued = 0
        for event in events:
            strategists = list(
                (
                    await self.session.scalars(
                        select(PortfolioStrategist)
                        .join(
                            PortfolioAsset,
                            PortfolioAsset.pas_prt_id == PortfolioStrategist.pst_prt_id,
                        )
                        .where(
                            PortfolioStrategist.pst_status == "active",
                            PortfolioAsset.pas_ast_id == event.moe_ast_id,
                            PortfolioAsset.pas_is_active.is_(True),
                        )
                    )
                ).all()
            )
            existing_strategist_ids = set(
                (
                    await self.session.scalars(
                        select(PortfolioStrategistRun.psr_pst_id).where(
                            PortfolioStrategistRun.psr_moe_id == event.moe_id
                        )
                    )
                ).all()
            )
            for strategist in strategists:
                if strategist.pst_id in existing_strategist_ids:
                    continue
                self.session.add(
                    PortfolioStrategistRun(
                        psr_pst_id=strategist.pst_id,
                        psr_ast_id=event.moe_ast_id,
                        psr_moe_id=event.moe_id,
                        psr_review_type="targeted_price",
                        psr_status="pending",
                        psr_priority=4,
                        psr_reason=event.moe_reason,
                    )
                )
                queued += 1
            event.moe_status = "notified"

        await self.session.commit()
        return queued

    async def queue_due_full_reviews(self, now: datetime | None = None) -> int:
        due_at = now or utc_now()
        strategists = list(
            (
                await self.session.scalars(
                    select(PortfolioStrategist)
                    .join(Portfolio, Portfolio.prt_id == PortfolioStrategist.pst_prt_id)
                    .where(
                        PortfolioStrategist.pst_status == "active",
                        Portfolio.prt_is_active.is_(True),
                        PortfolioStrategist.pst_next_full_review_at <= due_at,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        queued = 0
        for strategist in strategists:
            active_full = await self.session.scalar(
                select(PortfolioStrategistRun.psr_id)
                .where(
                    PortfolioStrategistRun.psr_pst_id == strategist.pst_id,
                    PortfolioStrategistRun.psr_review_type == "full",
                    PortfolioStrategistRun.psr_status.in_(("pending", "running")),
                )
                .limit(1)
            )
            if active_full is None:
                self.session.add(
                    PortfolioStrategistRun(
                        psr_pst_id=strategist.pst_id,
                        psr_review_type="full",
                        psr_status="pending",
                        psr_priority=3,
                        psr_reason="Scheduled two-hour portfolio and ideas review.",
                    )
                )
                queued += 1
            strategist.pst_next_full_review_at = due_at + FULL_REVIEW_INTERVAL
            strategist.pst_updated_at = due_at

        await self.session.commit()
        return queued

    async def queue_full_review(self, portfolio_id: int) -> PortfolioStrategistRun:
        strategist = await self.session.scalar(
            select(PortfolioStrategist).where(
                PortfolioStrategist.pst_prt_id == portfolio_id
            )
        )
        if strategist is None:
            raise LookupError(f"No strategist exists for portfolio {portfolio_id}")
        run = PortfolioStrategistRun(
            psr_pst_id=strategist.pst_id,
            psr_review_type="full",
            psr_status="pending",
            psr_priority=4,
            psr_reason="Manually requested full portfolio and ideas review.",
        )
        self.session.add(run)
        strategist.pst_next_full_review_at = utc_now() + FULL_REVIEW_INTERVAL
        strategist.pst_updated_at = utc_now()
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def claim_next_run(self) -> PortfolioStrategistRun | None:
        run = await self.session.scalar(
            select(PortfolioStrategistRun)
            .where(PortfolioStrategistRun.psr_status == "pending")
            .order_by(
                PortfolioStrategistRun.psr_priority.desc(),
                PortfolioStrategistRun.psr_created_at,
            )
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if run is None:
            return None
        run.psr_status = "running"
        run.psr_started_at = utc_now()
        run.psr_error = None
        await self.session.commit()
        return run

    async def claim_next_event(self) -> MarketOpportunityEvent | None:
        event = await self.session.scalar(
            select(MarketOpportunityEvent)
            .where(MarketOpportunityEvent.moe_status == "detected")
            .order_by(MarketOpportunityEvent.moe_detected_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if event is None:
            return None
        event.moe_status = "analyzing"
        event.moe_error = None
        await self.session.commit()
        return event
