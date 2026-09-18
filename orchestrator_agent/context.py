"""Context providers for the standalone orchestration cycle."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Analysis, AnalysisAsset, Asset, Signal
from orchestrator_agent.schemas import AnalysisSummary, SignalSnapshot


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc)


class ContextProvider(Protocol):
    async def recent_signals(
        self,
        since: datetime,
        until: datetime,
    ) -> list[SignalSnapshot]: ...

    async def analysis_history(
        self,
        asset_ids: set[int],
        until: datetime,
    ) -> list[AnalysisSummary]: ...


class DatabaseContextProvider:
    """Read signal and prior-analysis context from FAAH without mutating it."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def recent_signals(
        self,
        since: datetime,
        until: datetime,
    ) -> list[SignalSnapshot]:
        # The current columns are TIMESTAMP WITHOUT TIME ZONE and store UTC.
        start = _as_utc(since).replace(tzinfo=None)
        end = _as_utc(until).replace(tzinfo=None)
        rows = (
            await self.session.execute(
                select(Signal, Asset, Analysis)
                .join(Asset, Asset.ast_id == Signal.sig_ast_id)
                .join(Analysis, Analysis.anl_id == Signal.sig_anl_id)
                .where(
                    Signal.sig_created_at > start,
                    Signal.sig_created_at <= end,
                )
                .order_by(Signal.sig_created_at, Signal.sig_id)
            )
        ).all()
        return [
            SignalSnapshot(
                signal_id=signal.sig_id,
                analysis_id=signal.sig_anl_id,
                asset_id=asset.ast_id,
                asset_symbol=asset.ast_symbol,
                action=signal.sig_action,
                confidence=signal.sig_confidence,
                timeframe=signal.sig_timeframe,
                status=signal.sig_status,
                created_at=_as_utc(signal.sig_created_at),
                generating_analysis_summary=analysis.anl_summary,
            )
            for signal, asset, analysis in rows
        ]

    async def analysis_history(
        self,
        asset_ids: set[int],
        until: datetime,
    ) -> list[AnalysisSummary]:
        if not asset_ids:
            return []

        end = _as_utc(until).replace(tzinfo=None)
        rows = (
            await self.session.execute(
                select(Analysis, Asset)
                .outerjoin(
                    AnalysisAsset,
                    AnalysisAsset.aas_anl_id == Analysis.anl_id,
                )
                .join(
                    Asset,
                    or_(
                        Asset.ast_id == AnalysisAsset.aas_ast_id,
                        Asset.ast_id == Analysis.anl_ast_id,
                    ),
                )
                .where(
                    Asset.ast_id.in_(asset_ids),
                    Analysis.anl_created_at <= end,
                    Analysis.anl_summary.is_not(None),
                )
                .distinct()
                .order_by(Analysis.anl_created_at, Analysis.anl_id)
            )
        ).all()
        return [
            AnalysisSummary(
                analysis_id=analysis.anl_id,
                asset_id=asset.ast_id,
                asset_symbol=asset.ast_symbol,
                summary=analysis.anl_summary,
                direction=analysis.anl_direction,
                confidence=analysis.anl_confidence,
                risk_level=analysis.anl_risk_level,
                timeframe=analysis.anl_timeframe,
                created_at=_as_utc(analysis.anl_created_at),
            )
            for analysis, asset in rows
        ]


class StaticContextProvider:
    """In-memory provider used to exercise the loop without the main app."""

    def __init__(
        self,
        signals: list[SignalSnapshot],
        analyses: list[AnalysisSummary],
    ) -> None:
        self.signals = signals
        self.analyses = analyses

    async def recent_signals(
        self,
        since: datetime,
        until: datetime,
    ) -> list[SignalSnapshot]:
        return [signal for signal in self.signals if since < signal.created_at <= until]

    async def analysis_history(
        self,
        asset_ids: set[int],
        until: datetime,
    ) -> list[AnalysisSummary]:
        return [
            analysis
            for analysis in self.analyses
            if analysis.asset_id in asset_ids and analysis.created_at <= until
        ]
