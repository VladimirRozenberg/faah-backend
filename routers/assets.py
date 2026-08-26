"""Routes HTTP liées aux actions et à leur historique."""

from fastapi import APIRouter, HTTPException, Query

from services.market_data import (
    ALLOWED_PERIOD_INTERVALS,
    InvalidHistoryRequestError,
    MarketDataUnavailableError,
    UnknownSymbolError,
    market_data_service,
)

from schemas import (
    AssetListResponse,
    AssetSummary,
    CandleResponse,
)


# Toutes les routes de ce fichier commencent par /api et sont regroupées
# sous le titre « Marché » dans la documentation Swagger.
router = APIRouter(prefix="/api", tags=["Marché"])


def raise_http_error(error: Exception) -> None:
    """Convertit les erreurs du service en réponses HTTP compréhensibles."""

    if isinstance(error, UnknownSymbolError):
        raise HTTPException(
            status_code=404,
            detail=f"Le symbole {error} ne fait pas partie des dix actions disponibles.",
        ) from error
    if isinstance(error, InvalidHistoryRequestError):
        raise HTTPException(status_code=400, detail=str(error)) from error
    if isinstance(error, MarketDataUnavailableError):
        raise HTTPException(status_code=502, detail=str(error)) from error
    raise error


@router.get("/assets", response_model=AssetListResponse)
def list_assets() -> AssetListResponse:
    """Retourne les dix actions avec leur dernier prix et leur variation."""

    try:
        items = market_data_service.get_assets()
        return AssetListResponse(count=len(items), items=items)
    except Exception as error:
        raise_http_error(error)
        raise  # Cette ligne aide uniquement l'analyse statique de Python.


@router.get("/assets/{symbol}", response_model=AssetSummary)
def get_asset(symbol: str) -> AssetSummary:
    """Retourne les informations principales d'une action."""

    try:
        return market_data_service.get_asset(symbol)
    except Exception as error:
        raise_http_error(error)
        raise


@router.get("/assets/{symbol}/candles", response_model=CandleResponse)
def get_asset_candles(
    symbol: str,
    period: str = Query(default="1d", description="Exemples : 1d, 5d, 1mo, 1y"),
    interval: str = Query(default="5m", description="Exemples : 1m, 5m, 1h, 1d"),
) -> CandleResponse:
    """Retourne les bougies OHLCV qui serviront au graphique Avalonia."""

    try:
        return market_data_service.get_candles(symbol, period, interval)
    except Exception as error:
        raise_http_error(error)
        raise


@router.get("/history-options")
def history_options() -> dict[str, list[str]]:
    """Indique à Avalonia les périodes et intervalles autorisés."""

    return {
        period: sorted(intervals)
        for period, intervals in ALLOWED_PERIOD_INTERVALS.items()
    }

