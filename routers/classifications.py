"""Read-only routes for source classifications."""

from fastapi import APIRouter
from sqlalchemy import select

from db import DbSession
from models import DataSource, SourceClassification


router = APIRouter(prefix="/api", tags=["Source classifications"])


@router.get("/source-classifications")
async def list_source_classifications(db: DbSession) -> dict:
    """Return classifications with their source details, newest first."""

    result = await db.execute(
        select(
            *SourceClassification.__table__.c,
            DataSource.src_type.label("source_type"),
            DataSource.src_title.label("source_title"),
            DataSource.src_content.label("source_content"),
            DataSource.src_original_url.label("source_original_url"),
            DataSource.src_published_at.label("source_published_at"),
            DataSource.src_created_at.label("source_created_at"),
        )
        .join(
            DataSource,
            DataSource.src_id == SourceClassification.cls_src_id,
        )
        .order_by(
            SourceClassification.cls_created_at.desc(),
            SourceClassification.cls_id.desc(),
        )
    )
    items = [dict(row) for row in result.mappings().all()]

    return {
        "count": len(items),
        "items": items,
    }
