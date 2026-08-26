"""Route simple permettant de vérifier que le serveur fonctionne."""

from fastapi import APIRouter

from schemas import HealthResponse


router = APIRouter(tags=["Système"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Vérifie FastAPI sans appeler Yahoo Finance."""

    return HealthResponse(status="ok")

