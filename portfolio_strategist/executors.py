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
    AssetNiche,
    MarketOpportunityEvent,
    Niche,
    OrchestratorAnalysisJob,
    Portfolio,
    PortfolioAsset,
    PortfolioAssetTypePreference,
    PortfolioNichePreference,
    PortfolioRecommendation,
    PortfolioStrategist,
    PortfolioStrategistAttempt,
    PortfolioStrategistRun,
    PortfolioStrategistRunSignal,
    Signal,
)
from live_market.redis_client import get_latest_quote
from orchestrator_agent.follow_up import (
    FollowUpAnalysisRepository,
    resolve_asset_symbol,
)
from portfolio_strategist.brain import (
    LLMStrategistBrain,
    SYSTEM_INSTRUCTIONS as STRATEGIST_SYSTEM_INSTRUCTIONS,
    StrategistBrain,
    StrategistResponseValidationError,
    build_strategist_model_input,
)
from portfolio_strategist.repository import StrategistRepository, utc_now
from portfolio_strategist.schemas import (
    StrategistAnalysis,
    StrategistContext,
    StrategistEligibleAsset,
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
MAX_STRATEGIST_ATTEMPTS = 3
STRATEGIST_RETRY_DELAY_SECONDS = 2


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

    async def _review_with_retries(
        self,
        run: PortfolioStrategistRun,
        context: StrategistContext,
    ):
        """Persist every exact prompt and provider/validation failure."""

        errors = []
        last_error = None
        validation_feedback = None
        for attempt_number in range(1, MAX_STRATEGIST_ATTEMPTS + 1):
            model_input = build_strategist_model_input(context, validation_feedback)
            prompt = await record_prompt(
                self.repository.session,
                name=f"Portfolio strategist attempt {attempt_number}",
                prompt_type=f"strategist_{run.psr_review_type}",
                system_instructions=STRATEGIST_SYSTEM_INSTRUCTIONS,
                user_prompt=model_input,
            )
            attempt = PortfolioStrategistAttempt(
                psa_psr_id=run.psr_id,
                psa_prm_id=prompt.prm_id,
                psa_attempt=attempt_number,
                psa_status="running",
                psa_model=getattr(self.brain, "model", None),
            )
            self.repository.session.add(attempt)
            await self.repository.session.flush()
            attempt_id = attempt.psa_id
            run.psr_prm_id = prompt.prm_id
            await self.repository.session.commit()

            try:
                result = await self.brain.review(context, validation_feedback)
            except asyncio.CancelledError:
                await self.repository.session.rollback()
                attempt = await self.repository.session.get(
                    PortfolioStrategistAttempt,
                    attempt_id,
                )
                if attempt is not None:
                    attempt.psa_status = "failed"
                    attempt.psa_error = "Strategist attempt cancelled."
                    attempt.psa_completed_at = utc_now()
                    await self.repository.session.commit()
                raise
            except Exception as exc:
                last_error = exc
                message = f"Attempt {attempt_number}: {type(exc).__name__}: {exc}"
                errors.append(message)
                validation_feedback = (
                    str(exc)
                    if isinstance(exc, StrategistResponseValidationError)
                    else None
                )
                await self.repository.session.rollback()
                attempt = await self.repository.session.get(
                    PortfolioStrategistAttempt,
                    attempt_id,
                )
                if attempt is not None:
                    attempt.psa_status = "failed"
                    attempt.psa_error = message[:2_000]
                    attempt.psa_completed_at = utc_now()
                    await self.repository.session.commit()
                logger.exception(
                    "Strategist attempt failed: run_id=%s attempt=%d/%d",
                    run.psr_id,
                    attempt_number,
                    MAX_STRATEGIST_ATTEMPTS,
                )
                if attempt_number < MAX_STRATEGIST_ATTEMPTS:
                    await asyncio.sleep(STRATEGIST_RETRY_DELAY_SECONDS)
                    continue
                break

            attempt = await self.repository.session.get(
                PortfolioStrategistAttempt,
                attempt_id,
            )
            if attempt is not None:
                attempt.psa_status = "succeeded"
                attempt.psa_completed_at = utc_now()
                await self.repository.session.commit()
            return result

        detail = " | ".join(errors)
        raise RuntimeError(
            f"Strategist failed after {MAX_STRATEGIST_ATTEMPTS} attempts: {detail}"
        ) from last_error

    async def run_pending(self, limit: int = MAX_STRATEGIST_RUNS_PER_PASS) -> int:
        executions = 0
        while executions < limit and (run := await self.repository.claim_next_run()):
            executions += 1
            run_id = run.psr_id
            try:
                context = await self._build_context(run)
                brain_result = await self._review_with_retries(run, context)
                analysis_id = await self._save_result(
                    run,
                    context,
                    brain_result.decision.model_dump(mode="json"),
                    brain_result.raw_content,
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

        preferred_asset_types = list(
            (
                await self.repository.session.scalars(
                    select(PortfolioAssetTypePreference.pat_asset_type)
                    .where(
                        PortfolioAssetTypePreference.pat_prt_id == portfolio.prt_id
                    )
                    .order_by(PortfolioAssetTypePreference.pat_asset_type)
                )
            ).all()
        )
        preferred_niches = list(
            (
                await self.repository.session.scalars(
                    select(Niche)
                    .join(
                        PortfolioNichePreference,
                        PortfolioNichePreference.pnp_nic_id == Niche.nic_id,
                    )
                    .where(
                        PortfolioNichePreference.pnp_prt_id == portfolio.prt_id
                    )
                    .order_by(Niche.nic_category, Niche.nic_name)
                )
            ).all()
        )

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
        triggering_signals = []
        source_analysis_ids: set[int] = set()
        batched_signal_ids = select(
            PortfolioStrategistRunSignal.psrs_sig_id
        ).where(PortfolioStrategistRunSignal.psrs_psr_id == run.psr_id)
        signal_filter = Signal.sig_id.in_(batched_signal_ids)
        if run.psr_sig_id is not None:
            signal_filter = or_(signal_filter, Signal.sig_id == run.psr_sig_id)
        signal_rows = list(
            (
                await self.repository.session.execute(
                    select(Signal, Analysis, Asset)
                    .join(Analysis, Analysis.anl_id == Signal.sig_anl_id)
                    .join(Asset, Asset.ast_id == Signal.sig_ast_id)
                    .where(signal_filter)
                    .order_by(Signal.sig_id)
                )
            ).all()
        )
        if run.psr_sig_id is not None and not signal_rows:
            raise LookupError(f"Triggering signal disappeared: {run.psr_sig_id}")
        triggering_signals = [
            self._signal_schema(signal, analysis, asset)
            for signal, analysis, asset in signal_rows
        ]
        triggering_signal = next(
            (
                signal
                for signal in triggering_signals
                if signal.signal_id == run.psr_sig_id
            ),
            triggering_signals[0] if triggering_signals else None,
        )
        source_analysis_ids.update(analysis.anl_id for _, analysis, _ in signal_rows)

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

        all_assets = list(
            (
                await self.repository.session.scalars(
                    select(Asset).order_by(Asset.ast_symbol)
                )
            ).all()
        )
        assets_by_id = {asset.ast_id: asset for asset in all_assets}
        preferred_niche_ids = {niche.nic_id for niche in preferred_niches}
        niche_asset_ids: set[int] = set()
        if preferred_niche_ids:
            niche_asset_ids = set(
                (
                    await self.repository.session.scalars(
                        select(AssetNiche.ani_ast_id).where(
                            AssetNiche.ani_nic_id.in_(preferred_niche_ids)
                        )
                    )
                ).all()
            )

        candidate_ids = {asset.ast_id for asset in all_assets}
        if preferred_asset_types:
            candidate_ids &= {
                asset.ast_id
                for asset in all_assets
                if asset.ast_type in preferred_asset_types
            }
        if preferred_niche_ids:
            candidate_ids &= niche_asset_ids

        historical_ids: set[int] = set()
        historical_signal_ids: set[int] = set()
        for idea in recent_ideas:
            if idea.get("signal_id") is not None:
                historical_signal_ids.add(int(idea["signal_id"]))
            for opportunity in (idea.get("decision") or {}).get("opportunities", []):
                if not isinstance(opportunity, dict):
                    continue
                symbol = opportunity.get("asset_symbol")
                asset = resolve_asset_symbol(str(symbol), all_assets) if symbol else None
                if asset is not None:
                    historical_ids.add(asset.ast_id)
                if opportunity.get("signal_id") is not None:
                    historical_signal_ids.add(int(opportunity["signal_id"]))

        follow_up_rows = list(
            (
                await self.repository.session.scalars(
                    select(OrchestratorAnalysisJob)
                    .where(
                        OrchestratorAnalysisJob.oaj_requested_at
                        >= utc_now() - timedelta(days=7),
                    )
                    .order_by(
                        OrchestratorAnalysisJob.oaj_requested_at.desc(),
                        OrchestratorAnalysisJob.oaj_id.desc(),
                    )
                    .limit(30)
                )
            ).all()
        )
        research_ids = {job.oaj_ast_id for job in follow_up_rows}
        relevant_ids = held_ids | historical_ids | research_ids
        if run.psr_review_type == "full":
            relevant_ids |= candidate_ids
        if triggering_signal is not None:
            relevant_ids.add(triggering_signal.asset_id)
        relevant_ids.update(signal.asset_id for signal in triggering_signals)
        if triggering_event is not None:
            relevant_ids.add(int(triggering_event["asset_id"]))

        recent_signals: list[StrategistSignal] = []
        if run.psr_review_type == "full" and (relevant_ids or historical_signal_ids):
            since = (utc_now() - timedelta(hours=24)).replace(tzinfo=None)
            signal_filter = Signal.sig_created_at >= since
            if historical_signal_ids:
                signal_filter = or_(
                    signal_filter,
                    Signal.sig_id.in_(historical_signal_ids),
                )
            rows = (
                await self.repository.session.execute(
                    select(Signal, Analysis, Asset)
                    .join(Analysis, Analysis.anl_id == Signal.sig_anl_id)
                    .join(Asset, Asset.ast_id == Signal.sig_ast_id)
                    .where(
                        or_(
                            Signal.sig_ast_id.in_(relevant_ids),
                            Signal.sig_id.in_(historical_signal_ids),
                        ),
                        signal_filter,
                    )
                    .order_by(Signal.sig_created_at.desc(), Signal.sig_id.desc())
                    .limit(100)
                )
            ).all()
            for signal, analysis, asset in rows:
                relevant_ids.add(asset.ast_id)
                recent_signals.append(self._signal_schema(signal, analysis, asset))
                source_analysis_ids.add(analysis.anl_id)

        if relevant_ids:
            linked_analysis_ids = select(AnalysisAsset.aas_anl_id).where(
                AnalysisAsset.aas_ast_id.in_(relevant_ids)
            )
            recent_analysis_ids = list(
                (
                    await self.repository.session.scalars(
                        select(Analysis.anl_id)
                        .where(
                            or_(
                                Analysis.anl_ast_id.in_(relevant_ids),
                                Analysis.anl_id.in_(linked_analysis_ids),
                            )
                        )
                        .order_by(Analysis.anl_created_at.desc(), Analysis.anl_id.desc())
                        .limit(100 if run.psr_review_type == "full" else 12)
                    )
                ).all()
            )
            source_analysis_ids.update(recent_analysis_ids)

        for job in follow_up_rows:
            if job.oaj_result_anl_id is not None:
                source_analysis_ids.add(job.oaj_result_anl_id)
        analyses = await self._analysis_schemas(source_analysis_ids)

        recent_follow_up_jobs = []
        for job in follow_up_rows:
            asset = assets_by_id.get(job.oaj_ast_id)
            result = (
                await self.repository.session.get(Analysis, job.oaj_result_anl_id)
                if job.oaj_result_anl_id is not None
                else None
            )
            recent_follow_up_jobs.append(
                {
                    "job_id": job.oaj_id,
                    "asset_symbol": asset.ast_symbol if asset else None,
                    "question": job.oaj_question,
                    "reason": job.oaj_reason,
                    "status": job.oaj_status,
                    "result_analysis_id": job.oaj_result_anl_id,
                    "result_summary": result.anl_summary if result else None,
                    "error": job.oaj_error,
                }
            )

        analysis_links: dict[int, set[int]] = {}
        if source_analysis_ids:
            link_rows = (
                await self.repository.session.execute(
                    select(AnalysisAsset.aas_anl_id, AnalysisAsset.aas_ast_id).where(
                        AnalysisAsset.aas_anl_id.in_(source_analysis_ids)
                    )
                )
            ).all()
            for analysis_id, asset_id in link_rows:
                analysis_links.setdefault(asset_id, set()).add(analysis_id)
        for analysis in analyses:
            if analysis.asset_id is not None:
                analysis_links.setdefault(analysis.asset_id, set()).add(
                    analysis.analysis_id
                )

        signal_links: dict[int, set[int]] = {}
        for signal in recent_signals:
            signal_links.setdefault(signal.asset_id, set()).add(signal.signal_id)
        if triggering_signal is not None:
            signal_links.setdefault(triggering_signal.asset_id, set()).add(
                triggering_signal.signal_id
            )

        catalog_ids = relevant_ids | held_ids | historical_ids
        eligible_assets = []
        for asset in all_assets:
            if asset.ast_id not in catalog_ids:
                continue
            reasons = []
            if asset.ast_id in held_ids:
                reasons.append("holding")
            if asset.ast_id in candidate_ids:
                reasons.append("portfolio_preference")
            if asset.ast_id in research_ids:
                reasons.append("research_request")
            if asset.ast_id in historical_ids:
                reasons.append("historical_review")
            if asset.ast_id in signal_links:
                reasons.append("signal")
            eligible_assets.append(
                StrategistEligibleAsset(
                    asset_id=asset.ast_id,
                    symbol=asset.ast_symbol,
                    name=asset.ast_name,
                    asset_type=asset.ast_type,
                    eligibility_reasons=reasons,
                    supporting_signal_ids=sorted(signal_links.get(asset.ast_id, set())),
                    supporting_analysis_ids=sorted(
                        analysis_links.get(asset.ast_id, set())
                    ),
                )
            )

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
                "preferred_asset_types": preferred_asset_types,
                "preferred_niches": [
                    {
                        "id": niche.nic_id,
                        "name": niche.nic_name,
                        "category": niche.nic_category,
                    }
                    for niche in preferred_niches
                ],
            },
            instructions=strategist.pst_instructions,
            positions=positions,
            triggering_signal=triggering_signal,
            triggering_signals=triggering_signals,
            triggering_market_event=triggering_event,
            recent_signals=recent_signals,
            analyses=analyses,
            eligible_assets=eligible_assets,
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
    ) -> int:
        health_direction = {
            "good": "positive",
            "stable": "neutral",
            "watch": "mixed",
            "concern": "negative",
        }[decision["portfolio_health"]]
        db_analysis = Analysis(
            anl_prm_id=run.psr_prm_id,
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
        assets_by_symbol = {}
        if symbols:
            assets = list(
                (
                    await self.repository.session.scalars(
                        select(Asset).where(Asset.ast_symbol.in_(symbols))
                    )
                ).all()
            )
            assets_by_symbol = {
                asset.ast_symbol.strip().upper(): asset for asset in assets
            }
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

        portfolio_id = int(context.portfolio["portfolio_id"])
        for assessment in decision["holding_assessments"]:
            symbol = assessment["asset_symbol"].strip().upper()
            asset = assets_by_symbol.get(symbol)
            self.repository.session.add(
                PortfolioRecommendation(
                    prc_psr_id=run.psr_id,
                    prc_prt_id=portfolio_id,
                    prc_ast_id=asset.ast_id if asset is not None else None,
                    prc_kind="holding_assessment",
                    prc_asset_symbol=symbol,
                    prc_action=assessment["verdict"],
                    prc_reason=assessment["reason"],
                )
            )
        for opportunity in decision["opportunities"]:
            symbol = opportunity["asset_symbol"].strip().upper()
            asset = assets_by_symbol.get(symbol)
            self.repository.session.add(
                PortfolioRecommendation(
                    prc_psr_id=run.psr_id,
                    prc_prt_id=portfolio_id,
                    prc_ast_id=asset.ast_id if asset is not None else None,
                    prc_sig_id=opportunity.get("signal_id"),
                    prc_kind="opportunity",
                    prc_asset_symbol=symbol,
                    prc_action="opportunity",
                    prc_reason=opportunity["reason"],
                    prc_confidence=opportunity["confidence"],
                )
            )
        if decision.get("targeted_conclusion") and decision.get("targeted_reason"):
            targeted_symbol = None
            targeted_asset_id = run.psr_ast_id
            triggering_signals = context.triggering_signals or (
                [context.triggering_signal]
                if context.triggering_signal is not None
                else []
            )
            triggering_asset_ids = {signal.asset_id for signal in triggering_signals}
            if len(triggering_asset_ids) == 1:
                targeted_asset_id = next(iter(triggering_asset_ids))
                targeted_symbol = next(
                    signal.asset_symbol.strip().upper()
                    for signal in triggering_signals
                )
            elif not triggering_signals and context.triggering_signal is not None:
                targeted_symbol = context.triggering_signal.asset_symbol.strip().upper()
                targeted_asset_id = context.triggering_signal.asset_id
            elif targeted_asset_id is not None:
                targeted_asset = next(
                    (
                        position
                        for position in context.positions
                        if position.asset_id == targeted_asset_id
                    ),
                    None,
                )
                if targeted_asset is not None:
                    targeted_symbol = targeted_asset.symbol.strip().upper()
            self.repository.session.add(
                PortfolioRecommendation(
                    prc_psr_id=run.psr_id,
                    prc_prt_id=portfolio_id,
                    prc_ast_id=targeted_asset_id,
                    prc_sig_id=(
                        run.psr_sig_id if len(triggering_signals) <= 1 else None
                    ),
                    prc_kind="targeted_conclusion",
                    prc_asset_symbol=targeted_symbol,
                    prc_action=decision["targeted_conclusion"],
                    prc_reason=decision["targeted_reason"],
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
