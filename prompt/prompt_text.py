import asyncio
from fastapi import FastAPI, HTTPException, status
from venv import logger

import db
from sqlalchemy import select

import json
from decimal import Decimal

from models import (
    Analysis,
    AnalysisAsset,
    AnalysisSource,
    Asset,
    ClassificationAsset,
    ClassificationNiche,
    DataSource,
    Niche,
    Prompt,
    Signal,
    SourceClassification,
)
from db import DbSession
from openai import AsyncOpenAI
from datetime import datetime, timedelta, timezone
import logging
from typing import Literal
from pydantic import BaseModel, Field
import os
from assets.detection import detect_and_save_assets
from prompt.niche_assignment import format_niches_by_category
from prompt.price_context import get_price_context


client=AsyncOpenAI(
    api_key=os.getenv("FAAH_API_KEY"),
    base_url="https://api.deepseek.com"
    )


logger = logging.getLogger(__name__)


class ClassificationResult(BaseModel):
    cls_category: str
    cls_importance: str
    cls_sentiment: str
    cls_reason: str
    cls_should_trigger: bool
    niches: list[str] = Field(default_factory=list)


class AnalysisSignalResult(BaseModel):
    sig_asset_symbol: str = Field(min_length=1, max_length=50)
    sig_action: Literal["buy", "sell", "hold"]
    sig_entry_price: float | None = Field(default=None, gt=0)
    sig_stop_loss_price: float | None = Field(default=None, gt=0)
    sig_take_profit_price: float | None = Field(default=None, gt=0)
    sig_confidence: int = Field(ge=0, le=100)
    sig_timeframe: Literal[
        "short-term",
        "medium-term",
        "long-term",
        "multiple",
    ]
    sig_expires_at: None = None


class AssetAnalysisResult(BaseModel):
    symbol: str = Field(min_length=1, max_length=50)
    direction: Literal["negative", "neutral", "positive", "mixed"]
    confidence: int = Field(ge=0, le=100)
    timeframe: Literal[
        "short-term",
        "medium-term",
        "long-term",
        "multiple",
    ]
    reason: str


class FinancialAnalysisResult(BaseModel):
    anl_response_text: str
    anl_summary: str
    anl_direction: Literal["negative", "neutral", "positive", "mixed"]
    anl_market_sentiment: Literal[
        "bearish",
        "neutral",
        "bullish",
        "mixed",
    ]
    anl_confidence: int = Field(ge=0, le=100)
    anl_risk_level: Literal["low", "medium", "high"]
    anl_timeframe: Literal[
        "short-term",
        "medium-term",
        "long-term",
        "multiple",
    ]
    assets: list[AssetAnalysisResult] = Field(default_factory=list)
    signals: list[AnalysisSignalResult] = Field(default_factory=list)


def parse_classification(content: str | None) -> ClassificationResult:
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

    source = await db.get(DataSource, source_id)

    if source is None:
        logger.info("Source not found; skipping classification")
        return None

    published_at = source.src_published_at

    if published_at is not None:
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)

        source_age = datetime.now(timezone.utc) - published_at

        if source_age > timedelta(days=2):
            logger.info(
                "Skipping old source: src_id=%s, published_at=%s, age_hours=%.1f",
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


# Record exactly what was sent to the LLM
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
        reasoning={
            "effort": "none",},
    tools=[
        {
            "type": "web_search",
        }
    ],
    text={
        "format": {
            "type": "json_object"
        }
    },
)
    content = response.output_text

    print("RAW DEEPSEEK CONTENT:", repr(content))

    if not content:
        print(response.model_dump_json(indent=2))
        raise RuntimeError("DeepSeek returned empty output")


    classification_json = json.loads(content, strict=False)

    classification = ClassificationResult.model_validate(
    classification_json
)

    db_classification = SourceClassification(
    cls_src_id=source_id,
    cls_prm_id=db_prompt.prm_id,
    cls_category=classification.cls_category,
    cls_importance=classification.cls_importance,
    cls_sentiment=classification.cls_sentiment,
    cls_should_trigger=classification.cls_should_trigger,
    cls_reason=classification.cls_reason,
)

    # Stage INSERT
    db.add(db_classification)

    await db.flush()

    niches_by_name = {
        niche.nic_name.casefold(): niche
        for niche in niches
    }
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

    # Execute transaction
    await db.commit()

    # Reload generated values such as cls_id and cls_created_at
    await db.refresh(db_classification)

    classification_id = db_classification.cls_id

    try:
        await detect_and_save_assets(
            db_classification,
            db,
            client,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        await db.rollback()
        logger.exception(
            "Asset detection failed for classification %d",
            db_classification.cls_id,
        )

    if db_classification.cls_should_trigger:
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

    return db_classification, db_analysis if db_classification.cls_should_trigger else "It's not a source that should trigger an analysis"


def generate_classification_prompt(
    source: DataSource,
    niches: list[Niche],
) -> str:

    available_niches = format_niches_by_category(niches)

    return f"""
You are a financial information classifier.

Analyze the source below and determine its potential relevance to financial markets, companies, industries, or financial assets.

IMPORTANT:
- Do NOT determine whether the source contains investment advice.
- Determine whether the information itself could have financial significance.
- Consider both direct and indirect effects.
- Business performance, executive changes, product launches, regulation,
  lawsuits, demand changes, supply disruptions, geopolitical events,
  technological developments, and similar events may be financially relevant
  even when stock prices or investing are never explicitly mentioned.
- Do not assume that the information is necessarily true or accurate if information is unverified use websearch to verify.

Return ONLY valid JSON using EXACTLY this structure:

{{
    "cls_category": "string",
    "cls_importance": "low | medium | high",
    "cls_sentiment": "negative | neutral | positive",
    "cls_reason": "short explanation",
    "cls_should_trigger": true,
    "niches": ["Exact niche name"]
    
}}

Field definitions:

cls_category:
The primary category of the information.
Examples: technology, finance, politics, energy, healthcare,
consumer, industrials, entertainment, other.

cls_importance:
- low: unlikely to materially affect a company, asset, industry, or market
- medium: potentially meaningful financial or business impact
- high: potentially major financial or market impact

cls_sentiment:
The likely directional implication of the information:
- positive
- neutral
- negative


cls_reason:
Briefly explain why you chose the classification and whether the
information could matter financially. Here you should use web search to verify the information and provide a short explanation of your reasoning. Also VERY IMPORTAN!!! include a short sentence if u used web search or not.

cls_should_trigger:
Set to true ONLY when ALL of the following conditions are satisfied:

The information is sufficiently credible.
The information is financially significant enough to justify deeper analysis.
The information in this article is fresh meaning it is not old news (published within the last 48 hours)

If the source appears fabricated, generic, misleading, materially incomplete, or cannot be reasonably verified despite searching for a supposedly real and recent event, set cls_should_trigger to false.

niches:
Choose between 1 and 3 relevant niches from AVAILABLE NICHES below.
Use only exact niche names from that list.
Multiple niches are allowed only when each one clearly applies to the source.
Use "Other / Unclassified" when no specific niche clearly applies.


Do not add additional JSON fields.
Do not include markdown.
Do not include text before or after the JSON.
Do not include any commentary or disclaimers.
Do not write your promt in any language other than English.

AVAILABLE NICHES:
{available_niches}

SOURCE TYPE:
{source.src_type}

TITLE:
{source.src_title}

CONTENT:
{source.src_content}

PUBLISHED AT:
{source.src_published_at}


"""


async def analyze_source(
    source_id: int,
    classification_id: int,
    db: DbSession,
):
    source = await db.get(DataSource, source_id)

    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source not found",
        )

    classification = await db.get(
        SourceClassification,
        classification_id,
    )

    if not classification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Classification not found",
        )

    if classification.cls_src_id != source_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Classification does not belong to this source",
        )

    asset_context, linked_assets = await get_analysis_asset_context(
        classification_id,
        db,
    )

    prompt_text = generate_analysis_prompt(
        source=source,
        classification=classification,
        asset_context=asset_context,
    )

    # Record exactly what was sent to the LLM
    db_prompt = Prompt(
        prm_name="Source financial analysis",
        prm_type="analysis",
        prm_version=1,
        prm_prompt_text=prompt_text,
    )

    db.add(db_prompt)
    await db.flush()

    response = await client.responses.create(
        model="deepseek-v4-flash",

        instructions=(
            "You are a financial analyst performing detailed "
            "financial analysis of financially significant information."
        ),

        input=prompt_text,

        max_output_tokens=12000,

        reasoning={
            "effort": "high",
        },

        text={
            "format": {
                "type": "json_object",
            }
        },

        tools=[
            {
                "type": "web_search",
            }
        ],
    )

    content = response.output_text

    if not content or not content.strip():
        raise RuntimeError("DeepSeek returned empty analysis output")

    analysis = FinancialAnalysisResult.model_validate(
        json.loads(content, strict=False)
    )

    db_analysis = Analysis(
        anl_prm_id=db_prompt.prm_id,
        anl_cls_id=classification_id,

        # Not asset/portfolio-specific yet.
        anl_prt_id=None,
        anl_ast_id=None,

        anl_trigger_type="classification",
        anl_trigger_reason=classification.cls_reason,

        anl_response_text=analysis.anl_response_text,
        anl_summary=analysis.anl_summary,
        anl_direction=analysis.anl_direction,
        anl_market_sentiment=analysis.anl_market_sentiment,
        anl_confidence=analysis.anl_confidence,
        anl_risk_level=analysis.anl_risk_level,
        anl_timeframe=analysis.anl_timeframe,
    )

    db.add(db_analysis)

    # Need anl_id before creating the relationship row.
    await db.flush()

    db_analysis_source = AnalysisSource(
        ans_anl_id=db_analysis.anl_id,
        ans_src_id=source.src_id,
    )

    db.add(db_analysis_source)

    analyzed_asset_ids = set()
    for asset_analysis in analysis.assets:
        linked = linked_assets.get(asset_analysis.symbol.strip().upper())
        if linked is None:
            logger.warning(
                "Ignoring analysis for unlinked asset %s.",
                asset_analysis.symbol,
            )
            continue

        asset, price_context = linked
        if asset.ast_id in analyzed_asset_ids:
            logger.warning(
                "Ignoring duplicate analysis for asset %s.",
                asset.ast_symbol,
            )
            continue

        analyzed_asset_ids.add(asset.ast_id)
        db.add(
            AnalysisAsset(
                aas_anl_id=db_analysis.anl_id,
                aas_ast_id=asset.ast_id,
                aas_direction=asset_analysis.direction,
                aas_confidence=asset_analysis.confidence,
                aas_timeframe=asset_analysis.timeframe,
                aas_reason=asset_analysis.reason,
                aas_price_context=price_context,
            )
        )

    assets_by_symbol = {
        symbol: linked[0]
        for symbol, linked in linked_assets.items()
    }
    signaled_asset_ids = set()

    for generated_signal in analysis.signals:
        symbol = generated_signal.sig_asset_symbol.strip().upper()
        asset = assets_by_symbol.get(symbol)

        if asset is None:
            logger.warning(
                "Ignoring signal for unlinked asset %s.",
                symbol,
            )
            continue

        if asset.ast_id in signaled_asset_ids:
            logger.warning(
                "Ignoring duplicate signal for asset %s.",
                symbol,
            )
            continue

        signaled_asset_ids.add(asset.ast_id)

        entry_price = generated_signal.sig_entry_price
        stop_loss_price = generated_signal.sig_stop_loss_price
        take_profit_price = generated_signal.sig_take_profit_price

        if generated_signal.sig_action == "hold":
            entry_price = None
            stop_loss_price = None
            take_profit_price = None
        else:
            if generated_signal.sig_confidence < 70:
                logger.warning(
                    "Ignoring low-confidence %s signal for asset %s.",
                    generated_signal.sig_action,
                    symbol,
                )
                continue

            _, price_context = linked_assets[symbol]
            if entry_price is None and price_context is not None:
                entry_price = price_context.get("current_price")

            if not valid_signal_prices(
                generated_signal.sig_action,
                entry_price,
                stop_loss_price,
                take_profit_price,
            ):
                logger.warning(
                    "Ignoring signal with invalid prices for asset %s.",
                    symbol,
                )
                continue

        db.add(
            Signal(
                sig_anl_id=db_analysis.anl_id,
                sig_prt_id=None,
                sig_ast_id=asset.ast_id,
                sig_action=generated_signal.sig_action,
                sig_entry_price=(
                    Decimal(str(entry_price))
                    if entry_price is not None
                    else None
                ),
                sig_stop_loss_price=(
                    Decimal(str(stop_loss_price))
                    if stop_loss_price is not None
                    else None
                ),
                sig_take_profit_price=(
                    Decimal(str(take_profit_price))
                    if take_profit_price is not None
                    else None
                ),
                sig_confidence=generated_signal.sig_confidence,
                sig_timeframe=generated_signal.sig_timeframe,
                sig_status="active",
                sig_expires_at=generated_signal.sig_expires_at,
            )
        )

    await db.commit()
    await db.refresh(db_analysis)

    return db_analysis


async def get_analysis_asset_context(
    classification_id: int,
    db: DbSession,
) -> tuple[str, dict[str, tuple[Asset, dict | None]]]:
    """Return linked assets and their Yahoo Finance price context."""

    asset_rows = (
        await db.execute(
            select(Asset, ClassificationAsset)
            .join(
                ClassificationAsset,
                ClassificationAsset.cla_ast_id == Asset.ast_id,
            )
            .where(
                ClassificationAsset.cla_cls_id == classification_id,
                Asset.ast_is_tracked.is_(True),
            )
            .order_by(
                ClassificationAsset.cla_relevance_confidence.desc(),
                Asset.ast_symbol,
            )
        )
    ).all()

    if not asset_rows:
        return "No assets are linked to this classification.", {}

    async def load_context(asset: Asset) -> dict | None:
        try:
            context = await get_price_context(asset.ast_symbol)
            return context.model_dump(mode="json")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Price context unavailable for %s.",
                asset.ast_symbol,
            )
            return None

    price_contexts = await asyncio.gather(
        *(load_context(asset) for asset, _ in asset_rows)
    )

    blocks = []
    linked_assets = {}
    for (asset, link), price_context in zip(asset_rows, price_contexts):
        symbol = asset.ast_symbol.strip().upper()
        linked_assets[symbol] = (asset, price_context)
        blocks.append(
            json.dumps(
                {
                    "symbol": asset.ast_symbol,
                    "name": asset.ast_name,
                    "type": asset.ast_type,
                    "yahoo_type": asset.ast_yahoo_type,
                    "exchange": asset.ast_exchange,
                    "currency": asset.ast_currency,
                    "country": asset.ast_country,
                    "is_tracked": asset.ast_is_tracked,
                    "classification_confidence": (
                        link.cla_relevance_confidence
                    ),
                    "classification_reason": link.cla_reason,
                    "price_context": (
                        price_context
                        if price_context is not None
                        else "Unavailable from Yahoo Finance at analysis time"
                    ),
                },
                ensure_ascii=False,
            )
        )

    return "\n".join(blocks), linked_assets


def valid_signal_prices(
    action: str,
    entry: float | None,
    stop_loss: float | None,
    take_profit: float | None,
) -> bool:
    """Reject directional signals without an entry or with invalid levels."""

    if entry is None or entry <= 0:
        return False

    if action == "buy":
        if stop_loss is not None and stop_loss >= entry:
            return False
        if take_profit is not None and take_profit <= entry:
            return False
    elif action == "sell":
        if stop_loss is not None and stop_loss <= entry:
            return False
        if take_profit is not None and take_profit >= entry:
            return False
    else:
        return False

    return True


def generate_analysis_prompt(
    source: DataSource,
    classification: SourceClassification,
    asset_context: str,
) -> str:
    return f"""
You are a financial analyst performing a deeper analysis of information that
has already been identified as potentially financially significant.

Analyze the source and determine its likely financial implications.

The source itself is the primary evidence.
The classification is preliminary context from an earlier processing stage.
Use the classification to understand why the information was considered
important, but do NOT assume that the classification is necessarily correct,
complete, or sufficiently nuanced.

Your task is NOT merely to summarize the source.

Determine:
- what financially relevant event or development occurred
- why it may matter financially
- which company, companies, industries, commodities, assets, or markets may
  be affected
- whether those effects are direct or indirect
- the mechanisms through which the financial impact could occur
- the likely direction of the impact
- the likely market interpretation
- the relevant timeframe
- the major uncertainties, dependencies, risks, and counterarguments
- whether the source materially changes what could reasonably be expected
  about the affected company, asset, industry, or market

IMPORTANT:
- Base the analysis primarily on the supplied source.
- Use web search to verify the information from the URL given (if given)
- If u cant access the URL try to verify it using other web sources and when making your analysis include a short sentence if u used web search or not and what sources it corresponded to from the web search -Give url and title.
- Do not invent facts, prices, financial figures, company exposures, market
  reactions, or events that are not supported by the provided information.
- Reasonable financial inference is allowed when the connection is clearly
  explained.
- Clearly distinguish facts stated in the source from conclusions inferred
  from those facts.
- Consider both positive and negative implications.
- Consider important second-order effects when they logically follow from
  the source.
- Do not assume positive news means an asset price must rise.
- Do not assume negative news means an asset price must fall.
- Consider whether the event may already have been expected, whether its
  effects depend on future developments, and whether important information
  is still missing.
- When evidence is insufficient, preserve the uncertainty rather than filling
  gaps with assumptions.
- The classification sentiment and importance may be wrong. Independently
  determine the final direction, sentiment, risk, and confidence.
- Use the supplied Yahoo Finance price context instead of searching for a
  current price. Treat its timestamps and market-status fields carefully.
- When the market is closed, current_price is the latest available price, not
  a live open-market trade.
- A price move around the article is context, not proof that the article
  caused the move.
- If price context is unavailable for an asset, preserve that uncertainty.
- Do not provide personalized investment advice.
- Trading signals are analytical labels for market-intelligence purposes, not
  personalized investment recommendations or instructions to execute trades.
- Assess every asset in LINKED ASSETS in the assets array.
- Generate signals only for assets in LINKED ASSETS and copy each symbol
  exactly as provided.
- Generate at most one signal per asset.
- Use buy or sell only for a clear directional thesis with signal confidence
  of at least 70. Use hold for a materially relevant but non-actionable asset.
- Return an empty signals array if no linked asset has a supported signal.
- Never invent prices or false precision. Use supplied price context when
  setting levels, and use null when a defensible level cannot be established.

Return ONLY valid JSON using EXACTLY this structure:

{{
    "anl_response_text": "string",
    "anl_summary": "string",
    "anl_direction": "negative | neutral | positive | mixed",
    "anl_market_sentiment": "bearish | neutral | bullish | mixed",
    "anl_confidence": 0,
    "anl_risk_level": "low | medium | high",
    "anl_timeframe": "short-term | medium-term | long-term | multiple",
    "assets": [
        {{
            "symbol": "exact symbol from LINKED ASSETS",
            "direction": "negative | neutral | positive | mixed",
            "confidence": 0,
            "timeframe": "short-term | medium-term | long-term | multiple",
            "reason": "asset-specific financial reasoning"
        }}
    ],
    "signals": [
        {{
            "sig_asset_symbol": "exact symbol from LINKED ASSETS",
            "sig_action": "buy | sell | hold",
            "sig_entry_price": null,
            "sig_stop_loss_price": null,
            "sig_take_profit_price": null,
            "sig_confidence": 0,
            "sig_timeframe": "short-term | medium-term | long-term | multiple",
            "sig_expires_at": null
        }}
    ]
}}

FIELD DEFINITIONS:

anl_response_text:
The complete financial analysis.

It should explain the event, its financial significance, the affected entities
or markets, the causal mechanisms through which effects may occur, important
positive and negative implications, uncertainties, and the likely timeframe.

It should focus on interpretation and financial consequences rather than
simply repeating the source.

!! important list the urls and titles of any sources you used to verify the information in the source. If you did not use web search to verify the information, include a short sentence explaining why.
and whether they should be used for wider analysis or not. 

always include a short sentence if you used web search or not

anl_summary:
A concise summary of the most important conclusion from the analysis.
Prefer one to three sentences.

anl_direction:
The likely direction of the underlying financial implications.

- positive:
  The information is predominantly financially favorable.

- negative:
  The information is predominantly financially unfavorable.

- neutral:
  No meaningful directional financial implication can currently be
  established.

- mixed:
  There are materially important positive and negative implications.

anl_market_sentiment:
The likely directional interpretation by financial markets.

- bullish
- bearish
- neutral
- mixed

Market sentiment and underlying financial direction may differ when justified.

anl_confidence:
An integer from 0 to 100 representing confidence in the analysis.

Use higher confidence when the facts and financial transmission mechanisms
are relatively clear.

Use lower confidence when important facts are missing, future developments
are required, several materially different outcomes remain plausible, or the
source provides insufficient evidence.

anl_risk_level:
The degree of uncertainty, downside exposure, execution risk, or potential
financial significance involved.

- low
- medium
- high

anl_timeframe:
The primary period over which the financially important implications are
likely to develop.

- short-term
- medium-term
- long-term
- multiple

Use "multiple" when important effects occur across meaningfully different
time horizons.

assets:
Return one asset assessment for every symbol supplied in LINKED ASSETS.
Use the exact supplied Yahoo Finance symbol and do not add unlisted symbols.
Assess each asset independently because the same event may affect different
assets in different directions.

signals:
A list of concise, asset-specific analytical signals. Each signal must concern
an asset from LINKED ASSETS and must be supported by the source, the supplied
price context, and the
financial reasoning in the analysis. An asset may be directly or indirectly
affected, but an indirect effect must have a clear causal mechanism.

sig_action:
- buy: the information has a sufficiently supported favorable implication for
  this specific asset
- sell: the information has a sufficiently supported unfavorable implication
  for this specific asset
- hold: the asset is materially relevant, but the directional implications are
  neutral, balanced, or too uncertain for buy or sell

Do not assume that every asset in the same industry is affected in the same
direction. Evaluate every returned signal independently.

sig_confidence:
An integer from 0 to 100 representing confidence in this asset-specific signal.

sig_timeframe:
The main timeframe for this specific signal: short-term, medium-term,
long-term, or multiple.

sig_entry_price, sig_stop_loss_price, sig_take_profit_price:
Use the supplied current_price as entry when appropriate. The server will also
fill a missing buy/sell entry from current_price. For a buy, stop loss must be
below entry and take profit above entry. For a sell, stop loss must be above
entry and take profit below entry. Use null for unsupported levels. All price
fields must be null for hold.

sig_expires_at:
Always use null. Signal expiry is not inferred automatically.

Do not add additional JSON fields.
Do not include markdown.
Do not include text before or after the JSON.
Do not include commentary or disclaimers.
Write all output in English.


CLASSIFICATION CONTEXT:

CATEGORY:
{classification.cls_category}

IMPORTANCE:
{classification.cls_importance}

SENTIMENT:
{classification.cls_sentiment}

CLASSIFICATION REASON:
{classification.cls_reason}

LINKED ASSETS AND YAHOO FINANCE PRICE CONTEXT:
{asset_context}


SOURCE:

SOURCE TYPE:
{source.src_type}

TITLE:
{source.src_title}

CONTENT:
{source.src_content}

PUBLISHED AT:
{source.src_published_at}


"""
