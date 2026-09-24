"""Inspection and demo controls for portfolio strategists."""

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from db import DbSession
from models import MarketOpportunityEvent, PortfolioStrategist, PortfolioStrategistRun
from portfolio_strategist.repository import StrategistRepository


router = APIRouter(prefix="/api/strategists", tags=["Portfolio strategists"])


@router.get("")
async def list_strategists(db: DbSession) -> dict:
    strategists = list(
        (
            await db.scalars(
                select(PortfolioStrategist).order_by(PortfolioStrategist.pst_id)
            )
        ).all()
    )
    return {
        "count": len(strategists),
        "items": [
            {
                "strategist_id": item.pst_id,
                "portfolio_id": item.pst_prt_id,
                "status": item.pst_status,
                "instructions": item.pst_instructions,
                "last_signal_id": item.pst_last_signal_id,
                "last_full_review_at": item.pst_last_full_review_at,
                "next_full_review_at": item.pst_next_full_review_at,
                "last_summary": item.pst_last_summary,
            }
            for item in strategists
        ],
    }


@router.get("/events")
async def list_market_events(
    db: DbSession,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    events = list(
        (
            await db.scalars(
                select(MarketOpportunityEvent)
                .order_by(MarketOpportunityEvent.moe_detected_at.desc())
                .limit(limit)
            )
        ).all()
    )
    return {
        "count": len(events),
        "items": [
            {
                "event_id": item.moe_id,
                "asset_id": item.moe_ast_id,
                "event_type": item.moe_event_type,
                "price_before": float(item.moe_price_before),
                "price_after": float(item.moe_price_after),
                "change_pct": float(item.moe_change_pct),
                "window_seconds": item.moe_window_seconds,
                "reason": item.moe_reason,
                "status": item.moe_status,
                "analysis_id": item.moe_result_anl_id,
                "error": item.moe_error,
                "detected_at": item.moe_detected_at,
                "analyzed_at": item.moe_analyzed_at,
            }
            for item in events
        ],
    }


@router.get("/runs")
async def list_strategist_runs(
    db: DbSession,
    portfolio_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    statement = (
        select(PortfolioStrategistRun, PortfolioStrategist.pst_prt_id)
        .join(
            PortfolioStrategist,
            PortfolioStrategist.pst_id == PortfolioStrategistRun.psr_pst_id,
        )
        .order_by(PortfolioStrategistRun.psr_created_at.desc())
        .limit(limit)
    )
    if portfolio_id is not None:
        statement = statement.where(PortfolioStrategist.pst_prt_id == portfolio_id)
    rows = (await db.execute(statement)).all()
    return {
        "count": len(rows),
        "items": [
            {
                "run_id": run.psr_id,
                "strategist_id": run.psr_pst_id,
                "portfolio_id": resolved_portfolio_id,
                "review_type": run.psr_review_type,
                "status": run.psr_status,
                "priority": run.psr_priority,
                "asset_id": run.psr_ast_id,
                "signal_id": run.psr_sig_id,
                "market_event_id": run.psr_moe_id,
                "result_analysis_id": run.psr_result_anl_id,
                "reason": run.psr_reason,
                "decision": run.psr_decision,
                "error": run.psr_error,
                "created_at": run.psr_created_at,
                "completed_at": run.psr_completed_at,
            }
            for run, resolved_portfolio_id in rows
        ],
    }


@router.post("/portfolios/{portfolio_id}/full-review")
async def queue_full_review(portfolio_id: int, db: DbSession) -> dict:
    try:
        run = await StrategistRepository(db).queue_full_review(portfolio_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {
        "run_id": run.psr_id,
        "portfolio_id": portfolio_id,
        "status": run.psr_status,
        "message": "Full strategist review queued.",
    }
