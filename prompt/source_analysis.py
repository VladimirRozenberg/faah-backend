"""Detailed financial-analysis workflow for classified sources."""

import asyncio
import json
import logging
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select

from db import DbSession
from models import (
    Analysis,
    AnalysisAsset,
    AnalysisSource,
    Asset,
    ClassificationAsset,
    DataSource,
    Prompt,
    Signal,
    SourceClassification,
)
from prompt.llm_client import client
from prompt.price_context import get_price_context
from prompt.prompt_text import generate_analysis_prompt
from prompt.response_models import FinancialAnalysisResult


logger = logging.getLogger(__name__)


async def analyze_source(
    source_id: int,
    classification_id: int,
    db: DbSession,
):
    """Analyze a source using its classification and linked assets."""

    source = await db.get(DataSource, source_id)

    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source not found",
        )

    classification = await db.get(SourceClassification, classification_id)

    if not classification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Classification not found",
        )

    if classification.cls_src_id != source_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Classification does not belong to this source",
        )

    asset_context, linked_assets = await get_analysis_asset_context(
        classification_id,
        db,
    )

    prompt_text = generate_analysis_prompt(
        source=source,
        classification=classification,
        asset_context=asset_context,
    )

    # Record exactly what was sent to the LLM.
    db_prompt = Prompt(
        prm_name="Source financial analysis",
        prm_type="analysis",
        prm_version=1,
        prm_prompt_text=prompt_text,
    )

    db.add(db_prompt)
    await db.flush()

    response = await client.responses.create(
        model="deepseek-v4-flash",
        instructions=(
            "You are a financial analyst performing detailed "
            "financial analysis of financially significant information."
        ),
        input=prompt_text,
        max_output_tokens=12000,
        reasoning={"effort": "high"},
        text={"format": {"type": "json_object"}},
        tools=[{"type": "web_search"}],
    )

    content = response.output_text

    if not content or not content.strip():
        raise RuntimeError("DeepSeek returned empty analysis output")

    analysis = FinancialAnalysisResult.model_validate(
        json.loads(content, strict=False)
    )

    db_analysis = Analysis(
        anl_prm_id=db_prompt.prm_id,
        anl_cls_id=classification_id,
        # Not asset/portfolio-specific yet.
        anl_prt_id=None,
        anl_ast_id=None,
        anl_trigger_type="classification",
        anl_trigger_reason=classification.cls_reason,
        anl_response_text=analysis.anl_response_text,
        anl_summary=analysis.anl_summary,
        anl_direction=analysis.anl_direction,
        anl_market_sentiment=analysis.anl_market_sentiment,
        anl_confidence=analysis.anl_confidence,
        anl_risk_level=analysis.anl_risk_level,
        anl_timeframe=analysis.anl_timeframe,
    )

    db.add(db_analysis)
    await db.flush()

    db.add(
        AnalysisSource(
            ans_anl_id=db_analysis.anl_id,
            ans_src_id=source.src_id,
        )
    )

    save_asset_analyses(db, db_analysis, analysis, linked_assets)
    save_signals(db, db_analysis, analysis, linked_assets)

    await db.commit()
    await db.refresh(db_analysis)

    return db_analysis


def save_asset_analyses(
    db: DbSession,
    db_analysis: Analysis,
    analysis: FinancialAnalysisResult,
    linked_assets: dict[str, tuple[Asset, dict | None]],
) -> None:
    """Save each valid, non-duplicate asset assessment."""

    analyzed_asset_ids = set()

    for asset_analysis in analysis.assets:
        linked = linked_assets.get(asset_analysis.symbol.strip().upper())
        if linked is None:
            logger.warning(
                "Ignoring analysis for unlinked asset %s.",
                asset_analysis.symbol,
            )
            continue

        asset, price_context = linked
        if asset.ast_id in analyzed_asset_ids:
            logger.warning(
                "Ignoring duplicate analysis for asset %s.",
                asset.ast_symbol,
            )
            continue

        analyzed_asset_ids.add(asset.ast_id)
        db.add(
            AnalysisAsset(
                aas_anl_id=db_analysis.anl_id,
                aas_ast_id=asset.ast_id,
                aas_direction=asset_analysis.direction,
                aas_confidence=asset_analysis.confidence,
                aas_timeframe=asset_analysis.timeframe,
                aas_reason=asset_analysis.reason,
                aas_price_context=price_context,
            )
        )


def save_signals(
    db: DbSession,
    db_analysis: Analysis,
    analysis: FinancialAnalysisResult,
    linked_assets: dict[str, tuple[Asset, dict | None]],
) -> None:
    """Validate and save generated trading signals."""

    assets_by_symbol = {
        symbol: linked[0] for symbol, linked in linked_assets.items()
    }
    signaled_asset_ids = set()

    for generated_signal in analysis.signals:
        symbol = generated_signal.sig_asset_symbol.strip().upper()
        asset = assets_by_symbol.get(symbol)

        if asset is None:
            logger.warning("Ignoring signal for unlinked asset %s.", symbol)
            continue

        if asset.ast_id in signaled_asset_ids:
            logger.warning("Ignoring duplicate signal for asset %s.", symbol)
            continue

        signaled_asset_ids.add(asset.ast_id)

        entry_price = generated_signal.sig_entry_price
        stop_loss_price = generated_signal.sig_stop_loss_price
        take_profit_price = generated_signal.sig_take_profit_price

        if generated_signal.sig_action == "hold":
            entry_price = None
            stop_loss_price = None
            take_profit_price = None
        else:
            if generated_signal.sig_confidence < 70:
                logger.warning(
                    "Ignoring low-confidence %s signal for asset %s.",
                    generated_signal.sig_action,
                    symbol,
                )
                continue

            _, price_context = linked_assets[symbol]
            if entry_price is None and price_context is not None:
                entry_price = price_context.get("current_price")

            if not valid_signal_prices(
                generated_signal.sig_action,
                entry_price,
                stop_loss_price,
                take_profit_price,
            ):
                logger.warning(
                    "Ignoring signal with invalid prices for asset %s.",
                    symbol,
                )
                continue

        db.add(
            Signal(
                sig_anl_id=db_analysis.anl_id,
                sig_prt_id=None,
                sig_ast_id=asset.ast_id,
                sig_action=generated_signal.sig_action,
                sig_entry_price=(
                    Decimal(str(entry_price))
                    if entry_price is not None
                    else None
                ),
                sig_stop_loss_price=(
                    Decimal(str(stop_loss_price))
                    if stop_loss_price is not None
                    else None
                ),
                sig_take_profit_price=(
                    Decimal(str(take_profit_price))
                    if take_profit_price is not None
                    else None
                ),
                sig_confidence=generated_signal.sig_confidence,
                sig_timeframe=generated_signal.sig_timeframe,
                sig_status="active",
                sig_expires_at=generated_signal.sig_expires_at,
            )
        )


async def get_analysis_asset_context(
    classification_id: int,
    db: DbSession,
) -> tuple[str, dict[str, tuple[Asset, dict | None]]]:
    """Return linked assets and their Yahoo Finance price context."""

    asset_rows = (
        await db.execute(
            select(Asset, ClassificationAsset)
            .join(
                ClassificationAsset,
                ClassificationAsset.cla_ast_id == Asset.ast_id,
            )
            .where(
                ClassificationAsset.cla_cls_id == classification_id,
                Asset.ast_is_tracked.is_(True),
            )
            .order_by(
                ClassificationAsset.cla_relevance_confidence.desc(),
                Asset.ast_symbol,
            )
        )
    ).all()

    if not asset_rows:
        return "No assets are linked to this classification.", {}

    async def load_context(asset: Asset) -> dict | None:
        try:
            context = await get_price_context(asset.ast_symbol)
            return context.model_dump(mode="json")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Price context unavailable for %s.",
                asset.ast_symbol,
            )
            return None

    price_contexts = await asyncio.gather(
        *(load_context(asset) for asset, _ in asset_rows)
    )

    blocks = []
    linked_assets = {}
    for (asset, link), price_context in zip(asset_rows, price_contexts):
        symbol = asset.ast_symbol.strip().upper()
        linked_assets[symbol] = (asset, price_context)
        blocks.append(
            json.dumps(
                {
                    "symbol": asset.ast_symbol,
                    "name": asset.ast_name,
                    "type": asset.ast_type,
                    "yahoo_type": asset.ast_yahoo_type,
                    "exchange": asset.ast_exchange,
                    "currency": asset.ast_currency,
                    "country": asset.ast_country,
                    "is_tracked": asset.ast_is_tracked,
                    "classification_confidence": (
                        link.cla_relevance_confidence
                    ),
                    "classification_reason": link.cla_reason,
                    "price_context": (
                        price_context
                        if price_context is not None
                        else "Unavailable from Yahoo Finance at analysis time"
                    ),
                },
                ensure_ascii=False,
            )
        )

    return "\n".join(blocks), linked_assets


def valid_signal_prices(
    action: str,
    entry: float | None,
    stop_loss: float | None,
    take_profit: float | None,
) -> bool:
    """Reject directional signals without an entry or with invalid levels."""

    if entry is None or entry <= 0:
        return False

    if action == "buy":
        if stop_loss is not None and stop_loss >= entry:
            return False
        if take_profit is not None and take_profit <= entry:
            return False
    elif action == "sell":
        if stop_loss is not None and stop_loss <= entry:
            return False
        if take_profit is not None and take_profit >= entry:
            return False
    else:
        return False

    return True
