"""Read-only routes for generated financial analyses."""

from fastapi import APIRouter
from sqlalchemy import select

from db import DbSession
from models import Analysis, DataSource, SourceClassification


router = APIRouter(prefix="/api", tags=["Analyses"])


@router.get("/analyses")
async def list_analyses(db: DbSession) -> dict:
    """Return analyses with classification and source context, newest first."""

    result = await db.execute(
        select(
            *Analysis.__table__.c,
            SourceClassification.cls_category.label(
                "classification_category"
            ),
            SourceClassification.cls_importance.label(
                "classification_importance"
            ),
            SourceClassification.cls_sentiment.label(
                "classification_sentiment"
            ),
            SourceClassification.cls_reason.label(
                "classification_reason"
            ),
            DataSource.src_type.label("source_type"),
            DataSource.src_title.label("source_title"),
            DataSource.src_content.label("source_content"),
            DataSource.src_original_url.label("source_original_url"),
            DataSource.src_published_at.label("source_published_at"),
        )
        .outerjoin(
            SourceClassification,
            SourceClassification.cls_id == Analysis.anl_cls_id,
        )
        .outerjoin(
            DataSource,
            DataSource.src_id == SourceClassification.cls_src_id,
        )
        .order_by(
            Analysis.anl_created_at.desc(),
            Analysis.anl_id.desc(),
        )
    )
    items = [dict(row) for row in result.mappings().all()]

    return {
        "count": len(items),
        "items": items,
    }
