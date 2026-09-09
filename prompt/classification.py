"""Source-classification workflow.

Prompt wording lives in ``prompt_text.py`` so this module only contains the
steps needed to load, classify, and save a source.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from assets.detection import detect_and_save_assets
from db import DbSession
from models import (
    ClassificationNiche,
    DataSource,
    Niche,
    Prompt,
    SourceClassification,
)
from prompt.llm_client import client
from prompt.prompt_text import generate_classification_prompt
from prompt.response_models import ClassificationResult
from prompt.source_analysis import analyze_source


logger = logging.getLogger(__name__)


def parse_classification(content: str | None) -> ClassificationResult:
    """Validate a classification response, including fenced JSON."""

    if not content or not content.strip():
        raise ValueError("DeepSeek returned empty output")

    cleaned = content.strip()

    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json")
        cleaned = cleaned.removeprefix("```")
        cleaned = cleaned.removesuffix("```").strip()

    data = json.loads(cleaned, strict=False)
    return ClassificationResult.model_validate(data)


async def classify_source(source_id: int, db: DbSession):
    """Classify a recent source and run downstream analysis when needed."""

    source = await db.get(DataSource, source_id)

    if source is None:
        logger.info("Source not found; skipping classification")
        return None

    published_at = source.src_published_at

    if published_at is not None:
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)

        source_age = datetime.now(timezone.utc) - published_at

        if source_age > timedelta(hours=2):
            source.src_is_processed = True
            await db.commit()
            logger.info(
                "Discarded old source: src_id=%s, published_at=%s, age_hours=%.1f",
                source.src_id,
                published_at.isoformat(),
                source_age.total_seconds() / 3600,
            )
            return None

    source.src_is_processed = True

    niches = list(
        (
            await db.scalars(
                select(Niche).order_by(Niche.nic_category, Niche.nic_name)
            )
        ).all()
    )

    prompt_text = generate_classification_prompt(source, niches)

    # Record exactly what was sent to the LLM.
    db_prompt = Prompt(
        prm_name="Source classification",
        prm_type="classification",
        prm_version=1,
        prm_prompt_text=prompt_text,
    )

    db.add(db_prompt)
    await db.flush()

    response = await client.responses.create(
        model="deepseek-v4-flash",
        instructions="You are a financial information classifier.",
        input=prompt_text,
        max_output_tokens=4000,
        reasoning={"effort": "none"},
        tools=[{"type": "web_search"}],
        text={"format": {"type": "json_object"}},
    )

    classification = parse_classification(response.output_text)

    db_classification = SourceClassification(
        cls_src_id=source_id,
        cls_prm_id=db_prompt.prm_id,
        cls_category=classification.cls_category,
        cls_importance=classification.cls_importance,
        cls_sentiment=classification.cls_sentiment,
        cls_should_trigger=classification.cls_should_trigger,
        cls_reason=classification.cls_reason,
    )

    db.add(db_classification)
    await db.flush()

    niches_by_name = {niche.nic_name.casefold(): niche for niche in niches}
    selected_niches = []
    used_niche_ids = set()

    for selected_name in classification.niches[:3]:
        niche = niches_by_name.get(selected_name.strip().casefold())
        if niche is not None and niche.nic_id not in used_niche_ids:
            selected_niches.append(niche)
            used_niche_ids.add(niche.nic_id)

    if not selected_niches:
        fallback = niches_by_name.get("other / unclassified")
        if fallback is not None:
            selected_niches = [fallback]

    for niche in selected_niches:
        db.add(
            ClassificationNiche(
                cln_cls_id=db_classification.cls_id,
                cln_nic_id=niche.nic_id,
            )
        )

    await db.commit()
    await db.refresh(db_classification)
    classification_id = db_classification.cls_id
    should_trigger = db_classification.cls_should_trigger

    try:
        await detect_and_save_assets(db_classification, db, client)
    except asyncio.CancelledError:
        raise
    except Exception:
        await db.rollback()
        logger.exception(
            "Asset detection failed for classification %d",
            classification_id,
        )

    if not should_trigger:
        return (
            db_classification,
            "It's not a source that should trigger an analysis",
        )

    for attempt in range(1, 4):
        try:
            db_analysis = await analyze_source(
                source_id,
                classification_id,
                db,
            )
            break
        except Exception:
            await db.rollback()
            logger.exception(
                "Analysis failed: source_id=%s attempt=%d/3",
                source_id,
                attempt,
            )

            if attempt == 3:
                raise

            await asyncio.sleep(2)

    return db_classification, db_analysis
