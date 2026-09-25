"""Read-only routes for ingested data sources."""

from collections import defaultdict
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select

from db import DbSession
from models import (
    Analysis,
    AnalysisAsset,
    AnalysisInput,
    AnalysisSource,
    Asset,
    ClassificationAsset,
    ClassificationNiche,
    DataSource,
    Niche,
    Portfolio,
    Prompt,
    Signal,
    SourceClassification,
)

router = APIRouter(prefix="/api", tags=["Data sources"])


def _naive_utc(value: datetime | None) -> datetime | None:
    """Normalize API timestamps for the source tables' timezone-naive columns."""

    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _contains_pattern(value: str) -> str:
    escaped = value.strip().replace("\\", "\\\\")
    escaped = escaped.replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("/data-sources")
async def list_data_sources(
    db: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None, min_length=1, max_length=200),
    source_type: str | None = Query(default=None, min_length=1, max_length=100),
    is_processed: bool | None = Query(default=None),
    published_from: datetime | None = Query(default=None),
    published_to: datetime | None = Query(default=None),
    created_from: datetime | None = Query(default=None),
    created_to: datetime | None = Query(default=None),
    asset_symbol: str | None = Query(default=None, min_length=1, max_length=50),
    niche: str | None = Query(default=None, min_length=1, max_length=200),
    category: str | None = Query(default=None, min_length=1, max_length=100),
    importance: Literal["low", "medium", "high"] | None = Query(default=None),
    sentiment: Literal["negative", "neutral", "positive"] | None = Query(
        default=None
    ),
    should_trigger: bool | None = Query(default=None),
    sort_by: Literal["created_at", "published_at"] = Query(default="created_at"),
    sort_order: Literal["asc", "desc"] = Query(default="desc"),
) -> dict:
    """Return a filtered, paginated page of ingested sources."""

    published_from = _naive_utc(published_from)
    published_to = _naive_utc(published_to)
    created_from = _naive_utc(created_from)
    created_to = _naive_utc(created_to)
    if published_from and published_to and published_from > published_to:
        raise HTTPException(
            status_code=422,
            detail="published_from must be before or equal to published_to",
        )
    if created_from and created_to and created_from > created_to:
        raise HTTPException(
            status_code=422,
            detail="created_from must be before or equal to created_to",
        )

    conditions = []
    if q is not None and q.strip():
        pattern = _contains_pattern(q)
        conditions.append(
            or_(
                DataSource.src_title.ilike(pattern, escape="\\"),
                DataSource.src_content.ilike(pattern, escape="\\"),
                DataSource.src_original_url.ilike(pattern, escape="\\"),
            )
        )
    if source_type is not None and source_type.strip():
        conditions.append(
            func.lower(DataSource.src_type) == source_type.strip().lower()
        )
    if is_processed is not None:
        conditions.append(DataSource.src_is_processed.is_(is_processed))
    if published_from is not None:
        conditions.append(DataSource.src_published_at >= published_from)
    if published_to is not None:
        conditions.append(DataSource.src_published_at <= published_to)
    if created_from is not None:
        conditions.append(DataSource.src_created_at >= created_from)
    if created_to is not None:
        conditions.append(DataSource.src_created_at <= created_to)

    needs_classification = any(
        value is not None
        for value in (
            asset_symbol,
            niche,
            category,
            importance,
            sentiment,
            should_trigger,
        )
    )
    if needs_classification:
        related = select(1).select_from(SourceClassification)
        if asset_symbol is not None:
            related = related.join(
                ClassificationAsset,
                ClassificationAsset.cla_cls_id == SourceClassification.cls_id,
            ).join(Asset, Asset.ast_id == ClassificationAsset.cla_ast_id)
        if niche is not None:
            related = related.join(
                ClassificationNiche,
                ClassificationNiche.cln_cls_id == SourceClassification.cls_id,
            ).join(Niche, Niche.nic_id == ClassificationNiche.cln_nic_id)

        classification_conditions = [
            SourceClassification.cls_src_id == DataSource.src_id
        ]
        if asset_symbol is not None:
            classification_conditions.append(
                func.upper(Asset.ast_symbol) == asset_symbol.strip().upper()
            )
        if niche is not None:
            classification_conditions.append(
                func.lower(Niche.nic_name) == niche.strip().lower()
            )
        if category is not None:
            classification_conditions.append(
                func.lower(SourceClassification.cls_category)
                == category.strip().lower()
            )
        if importance is not None:
            classification_conditions.append(
                SourceClassification.cls_importance == importance
            )
        if sentiment is not None:
            classification_conditions.append(
                SourceClassification.cls_sentiment == sentiment
            )
        if should_trigger is not None:
            classification_conditions.append(
                SourceClassification.cls_should_trigger.is_(should_trigger)
            )
        conditions.append(related.where(*classification_conditions).exists())

    total = await db.scalar(
        select(func.count()).select_from(DataSource).where(*conditions)
    ) or 0

    sort_column = (
        DataSource.src_published_at
        if sort_by == "published_at"
        else DataSource.src_created_at
    )
    primary_order = (
        sort_column.asc().nulls_last()
        if sort_order == "asc"
        else sort_column.desc().nulls_last()
    )
    id_order = (
        DataSource.src_id.asc()
        if sort_order == "asc"
        else DataSource.src_id.desc()
    )

    result = await db.execute(
        select(*DataSource.__table__.c)
        .where(*conditions)
        .order_by(primary_order, id_order)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    items = [dict(row) for row in result.mappings().all()]
    source_ids = [item["src_id"] for item in items]

    related_assets: dict[int, list[str]] = {}

    if source_ids:
        links = await db.execute(
            select(
                SourceClassification.cls_src_id,
                Asset.ast_symbol,
            )
            .select_from(SourceClassification)
            .join(
                ClassificationAsset,
                ClassificationAsset.cla_cls_id
                == SourceClassification.cls_id,
            )
            .join(
                Asset,
                Asset.ast_id == ClassificationAsset.cla_ast_id,
            )
            .where(
                SourceClassification.cls_src_id.in_(source_ids)
            )
            .distinct()
            .order_by(
                SourceClassification.cls_src_id,
                Asset.ast_symbol,
            )
        )

        for source_id, symbol in links:
            related_assets.setdefault(source_id, []).append(symbol)

    for item in items:
        item["related_assets"] = related_assets.get(
            item["src_id"],
            [],
        )

    return {
        "count": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


@router.get("/data-sources/{source_id}")
async def get_data_source_details(source_id: int, db: DbSession) -> dict:
    """Return the complete classification and analysis story for one item."""

    source_result = await db.execute(
        select(*DataSource.__table__.c).where(DataSource.src_id == source_id)
    )
    source = source_result.mappings().one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Data source not found")

    classification_result = await db.execute(
        select(
            *SourceClassification.__table__.c,
            Prompt.prm_name.label("prompt_name"),
            Prompt.prm_type.label("prompt_type"),
            Prompt.prm_version.label("prompt_version"),
        )
        .join(Prompt, Prompt.prm_id == SourceClassification.cls_prm_id)
        .where(SourceClassification.cls_src_id == source_id)
        .order_by(
            SourceClassification.cls_created_at.asc(),
            SourceClassification.cls_id.asc(),
        )
    )
    classifications = [
        dict(row) for row in classification_result.mappings().all()
    ]
    classification_ids = [item["cls_id"] for item in classifications]

    assets_by_classification: dict[int, list[dict]] = defaultdict(list)
    niches_by_classification: dict[int, list[dict]] = defaultdict(list)
    if classification_ids:
        classified_asset_result = await db.execute(
            select(
                ClassificationAsset.cla_cls_id,
                ClassificationAsset.cla_prm_id,
                ClassificationAsset.cla_relevance_confidence,
                ClassificationAsset.cla_reason,
                Asset.ast_id,
                Asset.ast_symbol,
                Asset.ast_name,
                Asset.ast_type,
                Asset.ast_exchange,
                Asset.ast_currency,
                Asset.ast_country,
            )
            .join(Asset, Asset.ast_id == ClassificationAsset.cla_ast_id)
            .where(ClassificationAsset.cla_cls_id.in_(classification_ids))
            .order_by(
                ClassificationAsset.cla_cls_id.asc(),
                Asset.ast_symbol.asc(),
            )
        )
        for row in classified_asset_result.mappings().all():
            item = dict(row)
            classification_id = item.pop("cla_cls_id")
            assets_by_classification[classification_id].append(item)

        niche_result = await db.execute(
            select(
                ClassificationNiche.cln_cls_id,
                Niche.nic_id,
                Niche.nic_name,
                Niche.nic_category,
                Niche.nic_description,
            )
            .join(Niche, Niche.nic_id == ClassificationNiche.cln_nic_id)
            .where(ClassificationNiche.cln_cls_id.in_(classification_ids))
            .order_by(
                ClassificationNiche.cln_cls_id.asc(),
                Niche.nic_name.asc(),
            )
        )
        for row in niche_result.mappings().all():
            item = dict(row)
            classification_id = item.pop("cln_cls_id")
            niches_by_classification[classification_id].append(item)

    for classification in classifications:
        classification_id = classification["cls_id"]
        classification["assets"] = assets_by_classification[classification_id]
        classification["niches"] = niches_by_classification[classification_id]

    direct_analysis_result = await db.execute(
        select(AnalysisSource.ans_anl_id).where(
            AnalysisSource.ans_src_id == source_id
        )
    )
    directly_linked_analysis_ids = set(direct_analysis_result.scalars().all())

    related_analysis_condition = Analysis.anl_id.in_(
        directly_linked_analysis_ids
    )
    if classification_ids:
        related_analysis_condition = or_(
            Analysis.anl_cls_id.in_(classification_ids),
            related_analysis_condition,
        )

    analysis_result = await db.execute(
        select(
            *Analysis.__table__.c,
            Prompt.prm_name.label("prompt_name"),
            Prompt.prm_type.label("prompt_type"),
            Prompt.prm_version.label("prompt_version"),
        )
        .join(Prompt, Prompt.prm_id == Analysis.anl_prm_id)
        .where(related_analysis_condition)
        .order_by(Analysis.anl_created_at.asc(), Analysis.anl_id.asc())
    )
    analyses = [dict(row) for row in analysis_result.mappings().all()]
    analysis_ids = [item["anl_id"] for item in analyses]

    assets_by_analysis: dict[int, list[dict]] = defaultdict(list)
    signals_by_analysis: dict[int, list[dict]] = defaultdict(list)
    sources_by_analysis: dict[int, list[dict]] = defaultdict(list)
    inputs_by_analysis: dict[int, list[int]] = defaultdict(list)

    if analysis_ids:
        analyzed_asset_result = await db.execute(
            select(
                *AnalysisAsset.__table__.c,
                Asset.ast_symbol.label("asset_symbol"),
                Asset.ast_name.label("asset_name"),
                Asset.ast_type.label("asset_type"),
            )
            .join(Asset, Asset.ast_id == AnalysisAsset.aas_ast_id)
            .where(AnalysisAsset.aas_anl_id.in_(analysis_ids))
            .order_by(AnalysisAsset.aas_anl_id.asc(), Asset.ast_symbol.asc())
        )
        for row in analyzed_asset_result.mappings().all():
            item = dict(row)
            analysis_id = item.pop("aas_anl_id")
            assets_by_analysis[analysis_id].append(item)

        signal_result = await db.execute(
            select(
                *Signal.__table__.c,
                Asset.ast_symbol.label("asset_symbol"),
                Asset.ast_name.label("asset_name"),
                Asset.ast_type.label("asset_type"),
                Portfolio.prt_name.label("portfolio_name"),
            )
            .join(Asset, Asset.ast_id == Signal.sig_ast_id)
            .outerjoin(Portfolio, Portfolio.prt_id == Signal.sig_prt_id)
            .where(Signal.sig_anl_id.in_(analysis_ids))
            .order_by(Signal.sig_created_at.asc(), Signal.sig_id.asc())
        )
        for row in signal_result.mappings().all():
            item = dict(row)
            analysis_id = item["sig_anl_id"]
            signals_by_analysis[analysis_id].append(item)

        supporting_source_result = await db.execute(
            select(
                AnalysisSource.ans_anl_id,
                DataSource.src_id,
                DataSource.src_type,
                DataSource.src_title,
                DataSource.src_original_url,
                DataSource.src_published_at,
                DataSource.src_created_at,
            )
            .join(DataSource, DataSource.src_id == AnalysisSource.ans_src_id)
            .where(AnalysisSource.ans_anl_id.in_(analysis_ids))
            .order_by(
                AnalysisSource.ans_anl_id.asc(),
                DataSource.src_id.asc(),
            )
        )
        for row in supporting_source_result.mappings().all():
            item = dict(row)
            analysis_id = item.pop("ans_anl_id")
            item["is_requested_source"] = item["src_id"] == source_id
            sources_by_analysis[analysis_id].append(item)

        input_result = await db.execute(
            select(
                AnalysisInput.inp_anl_id,
                AnalysisInput.inp_src_anl_id,
            )
            .where(AnalysisInput.inp_anl_id.in_(analysis_ids))
            .order_by(
                AnalysisInput.inp_anl_id.asc(),
                AnalysisInput.inp_src_anl_id.asc(),
            )
        )
        for row in input_result.mappings().all():
            inputs_by_analysis[row.inp_anl_id].append(row.inp_src_anl_id)

    classification_id_set = set(classification_ids)
    for analysis in analyses:
        analysis_id = analysis["anl_id"]
        relationships = []
        if analysis.get("anl_cls_id") in classification_id_set:
            relationships.append("classification_result")
        if analysis_id in directly_linked_analysis_ids:
            relationships.append("supporting_source")
        analysis["relationships"] = relationships
        analysis["assets"] = assets_by_analysis[analysis_id]
        analysis["signals"] = signals_by_analysis[analysis_id]
        analysis["supporting_sources"] = sources_by_analysis[analysis_id]
        analysis["input_analysis_ids"] = inputs_by_analysis[analysis_id]

    signal_count = sum(len(item["signals"]) for item in analyses)
    return {
        "source": dict(source),
        "overview": {
            "classification_count": len(classifications),
            "analysis_count": len(analyses),
            "signal_count": signal_count,
            "detected_asset_count": len(
                {
                    asset["ast_id"]
                    for classification in classifications
                    for asset in classification["assets"]
                }
            ),
        },
        "classifications": classifications,
        "analyses": analyses,
    }
