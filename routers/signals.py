

"""Read-only routes for trading signals generated from analyses."""

from fastapi import APIRouter
from sqlalchemy import select

from db import DbSession
from models import Analysis, Asset, DataSource, Signal, SourceClassification
from models import Portfolio
from auth.login import CurrentUser
from sqlalchemy import or_, func


router = APIRouter(prefix="/api", tags=["Trading signals"])


@router.get("/opportunities")
async def list_opportunities(db: DbSession, user: CurrentUser) -> dict:
    owned = select(Portfolio.prt_id).where(Portfolio.prt_usr_id == user.user_id)
    result = await db.execute(
        select(Signal.sig_id, Signal.sig_action, Signal.sig_confidence,
               Signal.sig_timeframe, Signal.sig_created_at,
               Asset.ast_symbol.label("asset_symbol"), Asset.ast_name.label("asset_name"),
               Analysis.anl_summary.label("analysis_summary"))
        .join(Asset, Asset.ast_id == Signal.sig_ast_id)
        .join(Analysis, Analysis.anl_id == Signal.sig_anl_id)
        .where(Signal.sig_status == "active",
               func.lower(Signal.sig_action).in_(["buy", "sell"]),
               or_(Signal.sig_expires_at.is_(None), Signal.sig_expires_at > func.now()),
               or_(Signal.sig_prt_id.is_(None), Signal.sig_prt_id.in_(owned)),
               or_(Analysis.anl_prt_id.is_(None), Analysis.anl_prt_id.in_(owned)))
        .order_by(Signal.sig_created_at.desc(), Signal.sig_id.desc())
    )
    # Keep the latest active recommendation per asset, avoiding contradictory rows.
    items = []
    seen = set()
    for row in result.mappings():
        if row["asset_symbol"] not in seen:
            seen.add(row["asset_symbol"])
            items.append(dict(row))
    return {"count": len(items), "items": items}


@router.get("/trading-signals")
async def list_trading_signals(db: DbSession) -> dict:
    """Return signals with readable asset and analysis context, newest first."""

    signal_columns = [
        column
        for column in Signal.__table__.c
        if column.name != "sig_ast_id"
    ]

    result = await db.execute(
        select(
            *signal_columns,
            Asset.ast_symbol.label("asset_symbol"),
            Asset.ast_name.label("asset_name"),
            Asset.ast_type.label("asset_type"),
            Analysis.anl_summary.label("analysis_summary"),
            Analysis.anl_direction.label("analysis_direction"),
            Analysis.anl_market_sentiment.label(
                "analysis_market_sentiment"
            ),
            DataSource.src_title.label("source_title"),
            DataSource.src_original_url.label("source_original_url"),
        )
        .join(Asset, Asset.ast_id == Signal.sig_ast_id)
        .join(Analysis, Analysis.anl_id == Signal.sig_anl_id)
        .outerjoin(
            SourceClassification,
            SourceClassification.cls_id == Analysis.anl_cls_id,
        )
        .outerjoin(
            DataSource,
            DataSource.src_id == SourceClassification.cls_src_id,
        )
        .order_by(
            Signal.sig_created_at.desc(),
            Signal.sig_id.desc(),
        )
    )
    items = [dict(row) for row in result.mappings().all()]

    return {
        "count": len(items),
        "items": items,
    }

