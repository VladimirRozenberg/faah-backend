"""Consultation de la table niches depuis Swagger."""

from fastapi import APIRouter
from sqlalchemy import select

from db import DbSession
from models import Niche

router = APIRouter(prefix="/api", tags=["Niches"])


@router.get("/niches", summary="Afficher les niches enregistrées")
async def list_niches(db: DbSession) -> dict:
    """Retourne toutes les niches, triées par identifiant, sans modifier la base."""
    result = await db.execute(
        select(
            Niche.nic_id,
            Niche.nic_name,
            Niche.nic_category,
            Niche.nic_description,
        ).order_by(Niche.nic_id)
    )
    items = [dict(row) for row in result.mappings().all()]
    return {"count": len(items), "items": items}
