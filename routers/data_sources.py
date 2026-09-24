"""Read-only routes for ingested data sources."""

from collections import defaultdict

from fastapi import APIRouter, HTTPException
from sqlalchemy import or_, select

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


@router.get("/data-sources")
async def list_data_sources(db: DbSession) -> dict:
    """Return all data sources, newest first."""

    result = await db.execute(
        select(*DataSource.__table__.c).order_by(
            DataSource.src_created_at.desc(),
            DataSource.src_id.desc(),
        )
    )
    items = [dict(row) for row in result.mappings().all()]

    return {
        "count": len(items),
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
