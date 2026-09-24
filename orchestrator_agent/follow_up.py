"""Persistent execution of targeted analysis requested by the orchestrator."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
import os
import re

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    Analysis,
    AnalysisAsset,
    AnalysisInput,
    Asset,
    OrchestratorAnalysisJob,
)
from orchestrator_agent.schemas import AnalysisFollowUp, AnalysisFollowUpJobState
from prompt.llm_client import get_alibaba_client
from prompt.price_context import get_price_context
from prompt.recording import record_prompt
from prompt.response_models import FinancialAnalysisResult
from prompt.source_analysis import DEFAULT_ANALYSIS_MODEL, parse_analysis


logger = logging.getLogger(__name__)
MAX_PRIOR_ANALYSES = 12
MAX_JOBS_PER_PASS = 5


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc)


def asset_symbol_aliases(symbol: str) -> set[str]:
    """Return conservative comparison keys for common Yahoo ticker forms."""

    value = symbol.strip().upper()
    if not value:
        return set()

    aliases = {value, re.sub(r"[^A-Z0-9]", "", value)}
    if value.endswith(("=X", "=F")):
        stem = value[:-2]
        aliases.update({stem, re.sub(r"[^A-Z0-9]", "", stem)})
    return {alias for alias in aliases if alias}


def resolve_asset_symbol(symbol: str, assets: list[Asset]) -> Asset | None:
    """Resolve a model-written symbol only when the match is unambiguous."""

    requested = symbol.strip().upper()
    exact = [asset for asset in assets if asset.ast_symbol.strip().upper() == requested]
    if len(exact) == 1:
        return exact[0]

    requested_aliases = asset_symbol_aliases(requested)
    matches = [
        asset
        for asset in assets
        if requested_aliases.intersection(asset_symbol_aliases(asset.ast_symbol))
    ]
    return matches[0] if len(matches) == 1 else None


class FollowUpAnalysisRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def enqueue_many(
        self,
        requests: list[AnalysisFollowUp],
    ) -> list[AnalysisFollowUpJobState]:
        """Persist new requests while suppressing active and exact duplicates."""

        created: list[OrchestratorAnalysisJob] = []
        assets = list(
            (
                await self.session.scalars(
                    select(Asset).order_by(Asset.ast_id)
                )
            ).all()
        )
        for request in sorted(requests, key=lambda item: item.priority, reverse=True):
            symbol = request.asset_symbol.strip().upper()
            asset = resolve_asset_symbol(symbol, assets)
            if asset is None:
                logger.warning(
                    "Ignoring follow-up for unknown or ambiguous asset %s",
                    request.asset_symbol,
                )
                continue
            if asset.ast_symbol.strip().upper() != symbol:
                logger.info(
                    "Resolved follow-up asset alias %s to %s",
                    request.asset_symbol,
                    asset.ast_symbol,
                )

            active = await self.session.scalar(
                select(OrchestratorAnalysisJob.oaj_id)
                .where(
                    OrchestratorAnalysisJob.oaj_ast_id == asset.ast_id,
                    OrchestratorAnalysisJob.oaj_status.in_(("pending", "running")),
                )
                .limit(1)
            )
            if active is not None:
                logger.info("Follow-up already active for %s; skipping", symbol)
                continue

            duplicate = await self.session.scalar(
                select(OrchestratorAnalysisJob.oaj_id)
                .where(
                    OrchestratorAnalysisJob.oaj_ast_id == asset.ast_id,
                    func.lower(OrchestratorAnalysisJob.oaj_question)
                    == request.question.strip().lower(),
                    OrchestratorAnalysisJob.oaj_requested_at
                    >= utc_now() - timedelta(hours=24),
                )
                .limit(1)
            )
            if duplicate is not None:
                logger.info("Duplicate follow-up suppressed for %s", symbol)
                continue

            job = OrchestratorAnalysisJob(
                oaj_ast_id=asset.ast_id,
                oaj_question=request.question.strip(),
                oaj_reason=request.reason.strip(),
                oaj_priority=request.priority,
                oaj_status="pending",
            )
            self.session.add(job)
            await self.session.flush()
            created.append(job)

        await self.session.commit()
        return [await self._state(job) for job in created]

    async def list_states(
        self,
        *,
        since: datetime | None = None,
        asset_ids: set[int] | None = None,
        limit: int = 100,
    ) -> list[AnalysisFollowUpJobState]:
        statement = (
            select(OrchestratorAnalysisJob)
            .order_by(
                OrchestratorAnalysisJob.oaj_requested_at.desc(),
                OrchestratorAnalysisJob.oaj_id.desc(),
            )
            .limit(limit)
        )
        filters = []
        if since is not None or asset_ids:
            filters.append(
                OrchestratorAnalysisJob.oaj_status.in_(("pending", "running"))
            )
        if since is not None:
            filters.append(
                OrchestratorAnalysisJob.oaj_requested_at >= _as_utc(since)
            )
        if asset_ids:
            filters.append(OrchestratorAnalysisJob.oaj_ast_id.in_(asset_ids))
        if filters:
            statement = statement.where(or_(*filters))
        jobs = list((await self.session.scalars(statement)).all())
        return [await self._state(job) for job in jobs]

    async def claim_next(self) -> OrchestratorAnalysisJob | None:
        job = await self.session.scalar(
            select(OrchestratorAnalysisJob)
            .where(OrchestratorAnalysisJob.oaj_status == "pending")
            .order_by(
                OrchestratorAnalysisJob.oaj_priority.desc(),
                OrchestratorAnalysisJob.oaj_requested_at,
                OrchestratorAnalysisJob.oaj_id,
            )
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return None
        job.oaj_status = "running"
        job.oaj_started_at = utc_now()
        job.oaj_error = None
        await self.session.commit()
        return job

    async def succeed(self, job_id: int, analysis_id: int) -> None:
        job = await self.session.get(OrchestratorAnalysisJob, job_id)
        if job is None:
            raise LookupError(f"Follow-up job disappeared: {job_id}")
        job.oaj_status = "succeeded"
        job.oaj_result_anl_id = analysis_id
        job.oaj_completed_at = utc_now()
        job.oaj_error = None
        await self.session.commit()

    async def fail(self, job_id: int, error: str) -> None:
        job = await self.session.get(OrchestratorAnalysisJob, job_id)
        if job is None:
            raise LookupError(f"Follow-up job disappeared: {job_id}")
        job.oaj_status = "failed"
        job.oaj_completed_at = utc_now()
        job.oaj_error = error[:2_000]
        await self.session.commit()

    async def _state(
        self,
        job: OrchestratorAnalysisJob,
    ) -> AnalysisFollowUpJobState:
        asset = await self.session.get(Asset, job.oaj_ast_id)
        result = (
            await self.session.get(Analysis, job.oaj_result_anl_id)
            if job.oaj_result_anl_id is not None
            else None
        )
        return AnalysisFollowUpJobState(
            job_id=job.oaj_id,
            asset_id=job.oaj_ast_id,
            asset_symbol=asset.ast_symbol if asset is not None else "UNKNOWN",
            question=job.oaj_question,
            reason=job.oaj_reason,
            priority=job.oaj_priority,
            status=job.oaj_status,
            result_analysis_id=job.oaj_result_anl_id,
            result_summary=result.anl_summary if result is not None else None,
            result_text=result.anl_response_text if result is not None else None,
            error=job.oaj_error,
            requested_at=_as_utc(job.oaj_requested_at),
            started_at=(
                _as_utc(job.oaj_started_at) if job.oaj_started_at else None
            ),
            completed_at=(
                _as_utc(job.oaj_completed_at) if job.oaj_completed_at else None
            ),
        )


class FollowUpAnalysisExecutor:
    def __init__(self, repository: FollowUpAnalysisRepository):
        self.repository = repository

    async def run_pending(self, limit: int = MAX_JOBS_PER_PASS) -> int:
        executions = 0
        while executions < limit and (job := await self.repository.claim_next()):
            executions += 1
            job_id = job.oaj_id
            try:
                analysis_id = await self._execute(job)
                await self.repository.succeed(job_id, analysis_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self.repository.session.rollback()
                await self.repository.fail(job_id, str(exc))
                logger.exception("Follow-up analysis failed: job_id=%s", job_id)
        return executions

    async def _execute(self, job: OrchestratorAnalysisJob) -> int:
        asset = await self.repository.session.get(Asset, job.oaj_ast_id)
        if asset is None:
            raise LookupError(f"Follow-up asset disappeared: {job.oaj_ast_id}")

        linked_analysis_ids = select(AnalysisAsset.aas_anl_id).where(
            AnalysisAsset.aas_ast_id == asset.ast_id
        )
        prior = list(
            (
                await self.repository.session.scalars(
                    select(Analysis)
                    .where(
                        or_(
                            Analysis.anl_ast_id == asset.ast_id,
                            Analysis.anl_id.in_(linked_analysis_ids),
                        )
                    )
                    .order_by(Analysis.anl_created_at.desc(), Analysis.anl_id.desc())
                    .limit(MAX_PRIOR_ANALYSES)
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
            logger.exception(
                "Price context unavailable for follow-up asset %s", asset.ast_symbol
            )

        prompt_text = generate_follow_up_prompt(
            asset=asset,
            question=job.oaj_question,
            reason=job.oaj_reason,
            prior=prior,
            price_context=price_context,
        )
        system_instructions = (
            "You are a skeptical financial research analyst. Resolve "
            "the supplied follow-up question using the prior analyses "
            "as fallible context and current web research. Return JSON only."
        )
        db_prompt = await record_prompt(
            self.repository.session,
            name="Orchestrator targeted follow-up analysis",
            prompt_type="analysis_follow_up",
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
        content = response.choices[0].message.content
        result = parse_analysis(content)
        logger.info(
            "Alibaba follow-up response: job_id=%s asset=%s model=%s usage=%r",
            job.oaj_id,
            asset.ast_symbol,
            model,
            getattr(response, "usage", None),
        )

        db_analysis = Analysis(
            anl_prm_id=db_prompt.prm_id,
            anl_cls_id=None,
            anl_prt_id=None,
            anl_ast_id=asset.ast_id,
            anl_trigger_type="orchestrator_follow_up",
            anl_trigger_reason=job.oaj_question,
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
                aas_direction=(
                    asset_result.direction if asset_result else result.anl_direction
                ),
                aas_confidence=(
                    asset_result.confidence if asset_result else result.anl_confidence
                ),
                aas_timeframe=(
                    asset_result.timeframe if asset_result else result.anl_timeframe
                ),
                aas_reason=(
                    asset_result.reason if asset_result else result.anl_summary
                ),
                aas_price_context=price_context,
            )
        )
        for source_analysis in prior:
            self.repository.session.add(
                AnalysisInput(
                    inp_anl_id=db_analysis.anl_id,
                    inp_src_anl_id=source_analysis.anl_id,
                )
            )
        await self.repository.session.commit()
        return db_analysis.anl_id


def generate_follow_up_prompt(
    *,
    asset: Asset,
    question: str,
    reason: str,
    prior: list[Analysis],
    price_context: dict | None,
) -> str:
    history = [
        {
            "analysis_id": item.anl_id,
            "created_at": item.anl_created_at.isoformat(),
            "trigger_type": item.anl_trigger_type,
            "summary": item.anl_summary,
            "full_analysis": item.anl_response_text,
            "direction": item.anl_direction,
            "confidence": item.anl_confidence,
            "risk_level": item.anl_risk_level,
            "timeframe": item.anl_timeframe,
        }
        for item in reversed(prior)
    ]
    schema = FinancialAnalysisResult.model_json_schema()
    return f"""
Perform a targeted follow-up analysis for one financial asset.

FOLLOW-UP QUESTION:
{question}

WHY THE ORCHESTRATOR REQUESTED IT:
{reason}

ASSET:
{json.dumps({
    "symbol": asset.ast_symbol,
    "name": asset.ast_name,
    "type": asset.ast_type,
    "exchange": asset.ast_exchange,
    "currency": asset.ast_currency,
    "country": asset.ast_country,
}, ensure_ascii=False)}

CURRENT PRICE CONTEXT:
{json.dumps(price_context or "Unavailable", ensure_ascii=False)}

PRIOR ANALYSES, OLDEST TO NEWEST:
{json.dumps(history, ensure_ascii=False)}

Resolve the exact follow-up question rather than repeating the prior summaries.
Treat every prior analysis as fallible evidence: identify conflicts, stale claims,
unsupported assumptions, and what changed. Use current web search and prefer
primary sources, official filings, and reputable financial reporting. State
clearly when the available evidence cannot resolve the question. Include a
compact `Web sources:` line with titles and URLs in anl_response_text.

Return one entry for {asset.ast_symbol} in `assets`. Return an empty `signals`
array: this job provides evidence to the next orchestrator and must not create a
trade signal by itself. Return only JSON conforming to this schema:
{json.dumps(schema, ensure_ascii=False)}
""".strip()
