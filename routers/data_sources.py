"""Read-only routes for ingested data sources."""

from fastapi import APIRouter
from sqlalchemy import select

from db import DbSession
from models import DataSource


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
