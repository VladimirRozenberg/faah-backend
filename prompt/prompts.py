from fastapi import APIRouter, HTTPException, status

from assets.detection import (
    detect_and_save_assets,
    generate_asset_detection_prompt,
)
from models import DataSource, SourceClassification
from prompt.price_context import (
    PriceContext,
    PriceContextUnavailableError,
    get_price_context,
)
from prompt import prompt_text as prompts
from db import DbSession


router = APIRouter(tags=["Prompts"])


@router.get("/classify/{source_id}")
async def classify_source_endpoint(source_id: int, db: DbSession):
    classification = await prompts.classify_source(source_id, db)
    return classification


@router.get("/price-context/{symbol}", response_model=PriceContext)
async def price_context_endpoint(symbol: str) -> PriceContext:
    """Retourne un contexte de marché compact pour un futur prompt LLM."""

    try:
        return await get_price_context(symbol)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error
    except PriceContextUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error


@router.post("/test-asset-detection/{classification_id}")
async def test_asset_detection_endpoint(
    classification_id: int,
    db: DbSession,
):
    """Teste seulement la détection et l'enregistrement des actifs."""

    classification = await db.get(SourceClassification, classification_id)

    if classification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Classification not found",
        )

    source = await db.get(DataSource, classification.cls_src_id)

    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source linked to classification not found",
        )

    prompt_text = generate_asset_detection_prompt(classification, source)

    if not classification.cls_should_trigger:
        return {
            "status": "skipped",
            "classification_id": classification_id,
            "reason": "Classification is not marked for analysis",
            "prompt": prompt_text,
            "candidates": [],
            "saved_assets": [],
        }

    try:
        result, saved_assets = await detect_and_save_assets(
            classification,
            db,
            prompts.client,
        )
    except Exception as error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": "Asset detection failed",
                "error_type": type(error).__name__,
                "error": str(error),
            },
        ) from error

    return {
        "status": "completed",
        "classification_id": classification_id,
        "prompt": prompt_text,
        "candidate_count": len(result.assets),
        "saved_count": len(saved_assets),
        "candidates": [asset.model_dump() for asset in result.assets],
        "saved_assets": [
            {
                "id": asset.ast_id,
                "symbol": asset.ast_symbol,
                "name": asset.ast_name,
                "type": asset.ast_type,
                "exchange": asset.ast_exchange,
                "currency": asset.ast_currency,
            }
            for asset in saved_assets
        ],
    }


@router.get("/generate_analysis/{source_id}/{classification_id}")
async def generate_analysis_endpoint(
    source_id: int,
    classification_id: int,
    db: DbSession,
):
    analysis = await prompts.analyze_source(source_id, classification_id, db)
    return analysis
