"""Shared event analysis and portfolio strategist review executors."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
import os

from sqlalchemy import or_, select

from models import (
    Analysis,
    AnalysisAsset,
    AnalysisInput,
    Asset,
    MarketOpportunityEvent,
    OrchestratorAnalysisJob,
    Portfolio,
    PortfolioAsset,
    PortfolioStrategist,
    PortfolioStrategistRun,
    Signal,
)
from live_market.redis_client import get_latest_quote
from orchestrator_agent.follow_up import (
    FollowUpAnalysisRepository,
    resolve_asset_symbol,
)
from portfolio_strategist.brain import StrategistBrain, LLMStrategistBrain
from portfolio_strategist.repository import StrategistRepository, utc_now
from portfolio_strategist.schemas import (
    StrategistAnalysis,
    StrategistContext,
    StrategistPosition,
    StrategistSignal,
)
from prompt.llm_client import get_alibaba_client
from prompt.price_context import get_price_context
from prompt.recording import record_prompt
from prompt.response_models import FinancialAnalysisResult
from prompt.source_analysis import DEFAULT_ANALYSIS_MODEL, parse_analysis


logger = logging.getLogger(__name__)
MAX_EVENT_ANALYSES_PER_PASS = 3
MAX_STRATEGIST_RUNS_PER_PASS = 5


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc)


class MarketEventAnalysisExecutor:
    """Research a price event once before any portfolio strategist sees it."""

    def __init__(self, repository: StrategistRepository):
        self.repository = repository

    async def run_pending(self, limit: int = MAX_EVENT_ANALYSES_PER_PASS) -> int:
        executions = 0
        while executions < limit and (event := await self.repository.claim_next_event()):
            executions += 1
            event_id = event.moe_id
            try:
                analysis_id = await self._execute(event)
                event = await self.repository.session.get(
                    MarketOpportunityEvent,
                    event_id,
                )
                if event is None:
                    raise LookupError("Market event disappeared after analysis")
                event.moe_result_anl_id = analysis_id
                event.moe_status = "analyzed"
                event.moe_analyzed_at = utc_now()
                event.moe_error = None
                await self.repository.session.commit()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self.repository.session.rollback()
                failed = await self.repository.session.get(
                    MarketOpportunityEvent,
                    event_id,
                )
                if failed is not None:
                    failed.moe_status = "failed"
                    failed.moe_error = str(exc)[:2_000]
                    await self.repository.session.commit()
                logger.exception("Market-event analysis failed: event_id=%s", event_id)
        return executions

    async def _execute(self, event: MarketOpportunityEvent) -> int:
        asset = await self.repository.session.get(Asset, event.moe_ast_id)
        if asset is None:
            raise LookupError(f"Market-event asset disappeared: {event.moe_ast_id}")

        linked_ids = select(AnalysisAsset.aas_anl_id).where(
            AnalysisAsset.aas_ast_id == asset.ast_id
        )
        prior = list(
            (
                await self.repository.session.scalars(
                    select(Analysis)
                    .where(
                        or_(
                            Analysis.anl_ast_id == asset.ast_id,
                            Analysis.anl_id.in_(linked_ids),
                        )
                    )
                    .order_by(Analysis.anl_created_at.desc(), Analysis.anl_id.desc())
                    .limit(12)
                )
            ).all()
        )
        price_context = None
        try:
            price_context = (await get_price_context(asset.ast_symbol)).model_dump(
                mode="json"
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Price context unavailable for event %s", event.moe_id)

        prompt_text = (
            "Investigate this detected market-price event. Use current web research "
            "to look for credible causes. Clearly distinguish confirmed reporting, "
            "reasonable inference and an unexplained move. Evaluate whether the "
            "implications look temporary or structural. Do not produce a trading "
            "signal; return the standard financial-analysis JSON with signals=[].\n\n"
            f"EVENT\n{event.moe_reason}\n\n"
            f"CURRENT PRICE CONTEXT\n{json.dumps(price_context, default=str)}\n\n"
            "PRIOR ANALYSES (fallible context)\n"
            f"{json.dumps([{'analysis_id': item.anl_id, 'summary': item.anl_summary, 'created_at': item.anl_created_at.isoformat()} for item in prior], default=str)}\n\n"
            "REQUIRED OUTPUT JSON SCHEMA\n"
            f"{json.dumps(FinancialAnalysisResult.model_json_schema(), indent=2)}"
        )
        system_instructions = (
            "You are a skeptical market-event analyst. Research why the "
            "supplied movement may have occurred and return JSON only."
        )
        db_prompt = await record_prompt(
            self.repository.session,
            name="Market opportunity event analysis",
            prompt_type="market_event_analysis",
            system_instructions=system_instructions,
            user_prompt=prompt_text,
        )

        model = (
            os.getenv("FAAH_ALIBABA_ANALYSIS_MODEL", DEFAULT_ANALYSIS_MODEL).strip()
            or DEFAULT_ANALYSIS_MODEL
        )
        response = await get_alibaba_client().chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": system_instructions,
                },
                {"role": "user", "content": prompt_text},
            ],
            max_tokens=20_000,
            response_format={"type": "json_object"},
            extra_body={
                "enable_search": True,
                "search_options": {"search_strategy": "turbo"},
                "enable_thinking": False,
            },
        )
        result = parse_analysis(response.choices[0].message.content)
        db_analysis = Analysis(
            anl_prm_id=db_prompt.prm_id,
            anl_prt_id=None,
            anl_ast_id=asset.ast_id,
            anl_trigger_type="market_price_event",
            anl_trigger_reason=event.moe_reason,
            anl_response_text=result.anl_response_text,
            anl_summary=result.anl_summary,
            anl_direction=result.anl_direction,
            anl_market_sentiment=result.anl_market_sentiment,
            anl_confidence=result.anl_confidence,
            anl_risk_level=result.anl_risk_level,
            anl_timeframe=result.anl_timeframe,
        )
        self.repository.session.add(db_analysis)
        await self.repository.session.flush()

        asset_result = next(
            (
                item
                for item in result.assets
                if item.symbol.strip().upper() == asset.ast_symbol.strip().upper()
            ),
            None,
        )
        self.repository.session.add(
            AnalysisAsset(
                aas_anl_id=db_analysis.anl_id,
                aas_ast_id=asset.ast_id,
                aas_direction=(asset_result.direction if asset_result else result.anl_direction),
                aas_confidence=(asset_result.confidence if asset_result else result.anl_confidence),
                aas_timeframe=(asset_result.timeframe if asset_result else result.anl_timeframe),
                aas_reason=(asset_result.reason if asset_result else result.anl_summary),
                aas_price_context=price_context,
            )
        )
        for source in prior:
            self.repository.session.add(
                AnalysisInput(
                    inp_anl_id=db_analysis.anl_id,
                    inp_src_anl_id=source.anl_id,
                )
            )
        await self.repository.session.commit()
        return db_analysis.anl_id


class StrategistReviewExecutor:
    """Run queued targeted checks and scheduled full portfolio reviews."""

    def __init__(
        self,
        repository: StrategistRepository,
        brain: StrategistBrain | None = None,
    ) -> None:
        self.repository = repository
        self.brain = brain or LLMStrategistBrain()

    async def run_pending(self, limit: int = MAX_STRATEGIST_RUNS_PER_PASS) -> int:
        executions = 0
        while executions < limit and (run := await self.repository.claim_next_run()):
            executions += 1
            run_id = run.psr_id
            try:
                context = await self._build_context(run)
                brain_result = await self.brain.review(context)
                analysis_id = await self._save_result(
                    run,
                    context,
                    brain_result.decision.model_dump(mode="json"),
                    brain_result.raw_content,
                    brain_result.system_instructions,
                    brain_result.user_prompt,
                )
                follow_up_requests = await self._filter_recent_follow_ups(
                    brain_result.decision.follow_up_analysis
                )
                await FollowUpAnalysisRepository(
                    self.repository.session
                ).enqueue_many(follow_up_requests)

                run = await self.repository.session.get(PortfolioStrategistRun, run_id)
                strategist = await self.repository.session.get(
                    PortfolioStrategist,
                    run.psr_pst_id if run is not None else -1,
                )
                if run is None or strategist is None:
                    raise LookupError("Strategist run state disappeared")
                run.psr_status = "succeeded"
                run.psr_result_anl_id = analysis_id
                run.psr_decision = brain_result.decision.model_dump(mode="json")
                run.psr_completed_at = utc_now()
                run.psr_error = None
                strategist.pst_last_summary = brain_result.decision.summary
                strategist.pst_updated_at = utc_now()
                if run.psr_review_type == "full":
                    strategist.pst_last_full_review_at = utc_now()
                elif brain_result.decision.escalate_to_full_review:
                    strategist.pst_next_full_review_at = utc_now()
                await self.repository.session.commit()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self.repository.session.rollback()
                failed = await self.repository.session.get(
                    PortfolioStrategistRun,
                    run_id,
                )
                if failed is not None:
                    failed.psr_status = "failed"
                    failed.psr_error = str(exc)[:2_000]
                    failed.psr_completed_at = utc_now()
                    await self.repository.session.commit()
                logger.exception("Strategist review failed: run_id=%s", run_id)
        return executions

    async def _build_context(self, run: PortfolioStrategistRun) -> StrategistContext:
        strategist = await self.repository.session.get(
            PortfolioStrategist,
            run.psr_pst_id,
        )
        if strategist is None:
            raise LookupError(f"Strategist disappeared: {run.psr_pst_id}")
        portfolio = await self.repository.session.get(Portfolio, strategist.pst_prt_id)
        if portfolio is None:
            raise LookupError(f"Portfolio disappeared: {strategist.pst_prt_id}")

        position_rows = (
            await self.repository.session.execute(
                select(PortfolioAsset, Asset)
                .join(Asset, Asset.ast_id == PortfolioAsset.pas_ast_id)
                .where(
                    PortfolioAsset.pas_prt_id == portfolio.prt_id,
                    PortfolioAsset.pas_is_active.is_(True),
                )
                .order_by(Asset.ast_symbol)
            )
        ).all()
        positions = []
        for position, asset in position_rows:
            current_price = None
            try:
                quote = await get_latest_quote(asset.ast_symbol)
                current_price = quote.price if quote is not None else None
            except Exception:
                logger.exception("Live quote unavailable for %s", asset.ast_symbol)
            positions.append(
                StrategistPosition(
                    asset_id=asset.ast_id,
                    symbol=asset.ast_symbol,
                    name=asset.ast_name,
                    asset_type=asset.ast_type,
                    quantity=float(position.pas_quantity),
                    average_purchase_price=float(position.pas_average_purchase_price),
                    current_price=current_price,
                )
            )

        triggering_signal = None
        source_analysis_ids: set[int] = set()
        if run.psr_sig_id is not None:
            signal_row = (
                await self.repository.session.execute(
                    select(Signal, Analysis, Asset)
                    .join(Analysis, Analysis.anl_id == Signal.sig_anl_id)
                    .join(Asset, Asset.ast_id == Signal.sig_ast_id)
                    .where(Signal.sig_id == run.psr_sig_id)
                )
            ).one_or_none()
            if signal_row is None:
                raise LookupError(f"Triggering signal disappeared: {run.psr_sig_id}")
            signal, analysis, asset = signal_row
            triggering_signal = self._signal_schema(signal, analysis, asset)
            source_analysis_ids.add(analysis.anl_id)

        triggering_event = None
        if run.psr_moe_id is not None:
            event = await self.repository.session.get(
                MarketOpportunityEvent,
                run.psr_moe_id,
            )
            if event is None:
                raise LookupError(f"Triggering event disappeared: {run.psr_moe_id}")
            triggering_event = {
                "event_id": event.moe_id,
                "event_type": event.moe_event_type,
                "asset_id": event.moe_ast_id,
                "price_before": float(event.moe_price_before),
                "price_after": float(event.moe_price_after),
                "change_pct": float(event.moe_change_pct),
                "window_seconds": event.moe_window_seconds,
                "reason": event.moe_reason,
                "analysis_id": event.moe_result_anl_id,
            }
            if event.moe_result_anl_id is not None:
                source_analysis_ids.add(event.moe_result_anl_id)

        held_ids = {item.asset_id for item in positions}
        recent_signals: list[StrategistSignal] = []
        if run.psr_review_type == "full" and held_ids:
            since = (utc_now() - timedelta(hours=2)).replace(tzinfo=None)
            rows = (
                await self.repository.session.execute(
                    select(Signal, Analysis, Asset)
                    .join(Analysis, Analysis.anl_id == Signal.sig_anl_id)
                    .join(Asset, Asset.ast_id == Signal.sig_ast_id)
                    .where(
                        Signal.sig_ast_id.in_(held_ids),
                        Signal.sig_created_at >= since,
                    )
                    .order_by(Signal.sig_created_at.desc(), Signal.sig_id.desc())
                    .limit(100)
                )
            ).all()
            for signal, analysis, asset in rows:
                recent_signals.append(self._signal_schema(signal, analysis, asset))
                source_analysis_ids.add(analysis.anl_id)

        if held_ids:
            linked_analysis_ids = select(AnalysisAsset.aas_anl_id).where(
                AnalysisAsset.aas_ast_id.in_(held_ids)
            )
            recent_analysis_ids = list(
                (
                    await self.repository.session.scalars(
                        select(Analysis.anl_id)
                        .where(
                            or_(
                                Analysis.anl_ast_id.in_(held_ids),
                                Analysis.anl_id.in_(linked_analysis_ids),
                            )
                        )
                        .order_by(Analysis.anl_created_at.desc(), Analysis.anl_id.desc())
                        .limit(50 if run.psr_review_type == "full" else 12)
                    )
                ).all()
            )
            source_analysis_ids.update(recent_analysis_ids)

        analyses = await self._analysis_schemas(source_analysis_ids)
        recent_follow_up_jobs = []
        if held_ids:
            follow_up_rows = list(
                (
                    await self.repository.session.scalars(
                        select(OrchestratorAnalysisJob)
                        .where(
                            OrchestratorAnalysisJob.oaj_ast_id.in_(held_ids),
                            OrchestratorAnalysisJob.oaj_requested_at
                            >= utc_now() - timedelta(hours=24),
                        )
                        .order_by(
                            OrchestratorAnalysisJob.oaj_requested_at.desc(),
                            OrchestratorAnalysisJob.oaj_id.desc(),
                        )
                        .limit(30)
                    )
                ).all()
            )
            held_assets = {item.asset_id: item.symbol for item in positions}
            for job in follow_up_rows:
                result = (
                    await self.repository.session.get(Analysis, job.oaj_result_anl_id)
                    if job.oaj_result_anl_id is not None
                    else None
                )
                recent_follow_up_jobs.append(
                    {
                        "job_id": job.oaj_id,
                        "asset_symbol": held_assets.get(job.oaj_ast_id),
                        "question": job.oaj_question,
                        "reason": job.oaj_reason,
                        "status": job.oaj_status,
                        "result_analysis_id": job.oaj_result_anl_id,
                        "result_summary": result.anl_summary if result else None,
                        "error": job.oaj_error,
                    }
                )
        previous_rows = (
            await self.repository.session.execute(
                select(PortfolioStrategistRun)
                .where(
                    PortfolioStrategistRun.psr_pst_id == strategist.pst_id,
                    PortfolioStrategistRun.psr_status == "succeeded",
                    PortfolioStrategistRun.psr_decision.is_not(None),
                )
                .order_by(PortfolioStrategistRun.psr_completed_at.desc())
                .limit(20)
            )
        ).scalars().all()
        recent_ideas = [
            {
                "run_id": item.psr_id,
                "review_type": item.psr_review_type,
                "signal_id": item.psr_sig_id,
                "market_event_id": item.psr_moe_id,
                "completed_at": (
                    item.psr_completed_at.isoformat()
                    if item.psr_completed_at is not None
                    else None
                ),
                "decision": item.psr_decision,
            }
            for item in previous_rows
        ]
        return StrategistContext(
            review_type=run.psr_review_type,
            reason=run.psr_reason,
            portfolio={
                "portfolio_id": portfolio.prt_id,
                "name": portfolio.prt_name,
                "description": portfolio.prt_description,
                "strategy_type": portfolio.prt_strategy_type,
                "risk_tolerance": portfolio.prt_risk_tolerance,
                "max_position_size_pct": (
                    float(portfolio.prt_max_position_size_pct)
                    if portfolio.prt_max_position_size_pct is not None
                    else None
                ),
                "max_open_positions": portfolio.prt_max_open_positions,
                "base_currency": portfolio.prt_base_currency,
            },
            instructions=strategist.pst_instructions,
            positions=positions,
            triggering_signal=triggering_signal,
            triggering_market_event=triggering_event,
            recent_signals=recent_signals,
            analyses=analyses,
            recent_follow_up_jobs=recent_follow_up_jobs,
            recent_strategist_ideas=recent_ideas,
        )

    async def _filter_recent_follow_ups(self, requests):
        """Avoid repeated strategist research on one asset within two hours."""

        if not requests:
            return []
        assets = list((await self.repository.session.scalars(select(Asset))).all())
        accepted = []
        cutoff = utc_now() - timedelta(hours=2)
        for request in requests:
            asset = resolve_asset_symbol(request.asset_symbol, assets)
            if asset is None:
                accepted.append(request)
                continue
            recent = await self.repository.session.scalar(
                select(OrchestratorAnalysisJob.oaj_id)
                .where(
                    OrchestratorAnalysisJob.oaj_ast_id == asset.ast_id,
                    OrchestratorAnalysisJob.oaj_requested_at >= cutoff,
                    OrchestratorAnalysisJob.oaj_status.in_(
                        ("pending", "running", "succeeded")
                    ),
                )
                .limit(1)
            )
            if recent is not None:
                logger.info(
                    "Strategist follow-up suppressed by two-hour asset cooldown: %s",
                    asset.ast_symbol,
                )
                continue
            accepted.append(request)
        return accepted

    @staticmethod
    def _signal_schema(signal: Signal, analysis: Analysis, asset: Asset) -> StrategistSignal:
        return StrategistSignal(
            signal_id=signal.sig_id,
            analysis_id=analysis.anl_id,
            asset_id=asset.ast_id,
            asset_symbol=asset.ast_symbol,
            action=signal.sig_action,
            confidence=signal.sig_confidence,
            timeframe=signal.sig_timeframe,
            status=signal.sig_status,
            created_at=_as_utc(signal.sig_created_at),
            analysis_summary=analysis.anl_summary,
            analysis_risk_level=analysis.anl_risk_level,
        )

    async def _analysis_schemas(self, analysis_ids: set[int]) -> list[StrategistAnalysis]:
        if not analysis_ids:
            return []
        rows = list(
            (
                await self.repository.session.scalars(
                    select(Analysis)
                    .where(Analysis.anl_id.in_(analysis_ids))
                    .order_by(Analysis.anl_created_at, Analysis.anl_id)
                )
            ).all()
        )
        assets = {
            asset.ast_id: asset
            for asset in (
                await self.repository.session.scalars(
                    select(Asset).where(
                        Asset.ast_id.in_(
                            {item.anl_ast_id for item in rows if item.anl_ast_id is not None}
                        )
                    )
                )
            ).all()
        }
        return [
            StrategistAnalysis(
                analysis_id=item.anl_id,
                asset_id=item.anl_ast_id,
                asset_symbol=(
                    assets[item.anl_ast_id].ast_symbol
                    if item.anl_ast_id in assets
                    else None
                ),
                trigger_type=item.anl_trigger_type,
                summary=item.anl_summary,
                direction=item.anl_direction,
                confidence=item.anl_confidence,
                risk_level=item.anl_risk_level,
                timeframe=item.anl_timeframe,
                created_at=_as_utc(item.anl_created_at),
            )
            for item in rows
        ]

    async def _save_result(
        self,
        run: PortfolioStrategistRun,
        context: StrategistContext,
        decision: dict,
        raw_content: str,
        system_instructions: str,
        user_prompt: str,
    ) -> int:
        db_prompt = await record_prompt(
            self.repository.session,
            name=(
                "Portfolio strategist full review"
                if run.psr_review_type == "full"
                else "Portfolio strategist targeted review"
            ),
            prompt_type=f"strategist_{run.psr_review_type}",
            system_instructions=system_instructions,
            user_prompt=user_prompt,
        )
        run.psr_prm_id = db_prompt.prm_id
        health_direction = {
            "good": "positive",
            "stable": "neutral",
            "watch": "mixed",
            "concern": "negative",
        }[decision["portfolio_health"]]
        db_analysis = Analysis(
            anl_prm_id=db_prompt.prm_id,
            anl_prt_id=int(context.portfolio["portfolio_id"]),
            anl_ast_id=run.psr_ast_id,
            anl_trigger_type=f"strategist_{run.psr_review_type}",
            anl_trigger_reason=run.psr_reason,
            anl_response_text=raw_content,
            anl_summary=decision["summary"],
            anl_direction=health_direction,
            anl_market_sentiment="mixed",
            anl_confidence=None,
            anl_risk_level=context.portfolio.get("risk_tolerance"),
            anl_timeframe="multiple" if run.psr_review_type == "full" else "short-term",
        )
        self.repository.session.add(db_analysis)
        await self.repository.session.flush()

        symbols = {
            item["asset_symbol"].strip().upper()
            for item in decision["holding_assessments"] + decision["opportunities"]
        }
        if symbols:
            assets = list(
                (
                    await self.repository.session.scalars(
                        select(Asset).where(Asset.ast_symbol.in_(symbols))
                    )
                ).all()
            )
            reasons = {
                item["asset_symbol"].strip().upper(): item["reason"]
                for item in decision["holding_assessments"] + decision["opportunities"]
            }
            for asset in assets:
                self.repository.session.add(
                    AnalysisAsset(
                        aas_anl_id=db_analysis.anl_id,
                        aas_ast_id=asset.ast_id,
                        aas_direction=None,
                        aas_confidence=None,
                        aas_timeframe=None,
                        aas_reason=reasons.get(asset.ast_symbol.strip().upper()),
                        aas_price_context=None,
                    )
                )
        for source in context.analyses:
            self.repository.session.add(
                AnalysisInput(
                    inp_anl_id=db_analysis.anl_id,
                    inp_src_anl_id=source.analysis_id,
                )
            )
        await self.repository.session.commit()
        return db_analysis.anl_id
