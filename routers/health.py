"""Route de disponibilité de l'API."""

from fastapi import APIRouter

from schemas import HealthResponse


router = APIRouter(tags=["Système"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Vérifie FastAPI sans appeler Yahoo Finance."""

    # Confirme que FastAPI répond ; ne teste pas PostgreSQL, Redis ou Yahoo.
    return HealthResponse(status="ok")
