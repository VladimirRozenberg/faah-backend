"""Read-only routes for ingested data sources."""

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from db import DbSession
from models import (
    DataSource,
    SourceClassification,
    ClassificationAsset,
    Asset,
)

router = APIRouter(prefix="/api", tags=["Data sources"])


@router.get("/data-sources")
async def list_data_sources(
    db: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    """Retourne uniquement la page d'actualités demandée."""

    total = await db.scalar(
        select(func.count()).select_from(DataSource)
    ) or 0

    result = await db.execute(
        select(*DataSource.__table__.c)
        .order_by(
            DataSource.src_created_at.desc(),
            DataSource.src_id.desc(),
        )
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
