"""Détecte les actifs concernés après une classification positive."""

import asyncio
import json
import logging

from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from assets.repository import save_detected_assets
from assets.schemas import DetectedAsset
from models import Asset, SourceClassification


logger = logging.getLogger(__name__)


class AssetDetectionResult(BaseModel):
    """Format JSON attendu de DeepSeek."""

    assets: list[DetectedAsset] = Field(default_factory=list)


def generate_asset_detection_prompt(
    classification: SourceClassification,
) -> str:
    """Construit le prompt à partir du résumé de la classification."""

    return f"""
You identify financial assets from a financial classification summary.

Return ONLY valid JSON using EXACTLY this structure:

{{
    "assets": [
        {{
            "symbol": "AAPL",
            "confidence": 90,
            "reason": "Apple is directly affected by the event"
        }}
    ]
}}

Rules:
- Return the exact Yahoo Finance symbols.
- Examples: AAPL, BTC-USD, EURUSD=X or GC=F.
- Return at most the 10 most relevant assets.
- Only return equities, cryptocurrencies, forex pairs or futures.
- Keep only assets with a clear link to the event.
- Do not list every company from the same sector.
- Do not include a symbol if you are uncertain that it is correct.
- confidence must be an integer from 0 to 100.
- If no precise asset can be identified, return an empty assets list.
- Do not include markdown or text outside the JSON.

CLASSIFICATION REASON:
{classification.cls_reason}
"""


async def detect_and_save_assets(
    classification: SourceClassification,
    db: AsyncSession,
    client: AsyncOpenAI,
) -> list[Asset]:
    """Vérifie le trigger, trouve les symboles puis les enregistre."""

    if not classification.cls_should_trigger:
        return []

    try:
        prompt = generate_asset_detection_prompt(classification)

        response = await client.responses.create(
            model="deepseek-v4-flash",
            instructions="You identify Yahoo Finance asset symbols.",
            input=prompt,
            max_output_tokens=2000,
            reasoning={"effort": "none"},
            tools=[{"type": "web_search"}],
            text={"format": {"type": "json_object"}},
        )

        content = response.output_text
        if not content:
            raise ValueError("DeepSeek returned no asset")

        result = AssetDetectionResult.model_validate(
            json.loads(content, strict=False)
        )

        assets = await save_detected_assets(
            db,
            classification.cls_id,
            result.assets,
        )

        logger.info(
            "%d asset(s) found for classification %d",
            len(assets),
            classification.cls_id,
        )
        return assets

    except asyncio.CancelledError:
        raise

    except Exception:
        await db.rollback()
        logger.exception(
            "Asset detection failed for classification %d",
            classification.cls_id,
        )
        return []
