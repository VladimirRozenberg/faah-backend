import db
from sqlalchemy import select

import json

from models import DataSource, Prompt, SourceClassification, Analysis, AnalysisSource
from db import DbSession
from openai import AsyncOpenAI


client=AsyncOpenAI(
    api_key="sk-ad460ae7b7ae4bcfbd1e637eb33c5771",
    base_url="https://api.deepseek.com"
    )


async def classify_source(source_id: int, db: DbSession):
    source = await db.get(DataSource, source_id)

    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source not found",
        )


    prompt_text = generate_classification_prompt(source)

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


    classification = json.loads(content)

    db_classification = SourceClassification(
        cls_src_id=source_id,
        cls_prm_id=db_prompt.prm_id,
        cls_category=classification["cls_category"],
        cls_importance=classification["cls_importance"],
        cls_sentiment=classification["cls_sentiment"],
        cls_should_trigger=classification["cls_should_trigger"],
        cls_reason=classification["cls_reason"],
    )

    # Stage INSERT
    db.add(db_classification)

    

    # Execute transaction
    await db.commit()

    # Reload generated values such as cls_id and cls_created_at
    await db.refresh(db_classification)

    if db_classification.cls_should_trigger:
           db_analysis = await analyze_source(source_id, db_classification.cls_id, db)

    return db_classification, db_analysis if db_classification.cls_should_trigger else "its fake news"


def generate_classification_prompt(source: DataSource) -> str:

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
    "cls_should_trigger": true
    
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
Set to true ONLY when BOTH of the following conditions are satisfied:

The information is sufficiently credible.
The information is financially significant enough to justify deeper analysis.

If the source appears fabricated, generic, misleading, materially incomplete, or cannot be reasonably verified despite searching for a supposedly real and recent event, set cls_should_trigger to false.


Do not add additional JSON fields.
Do not include markdown.
Do not include text before or after the JSON.
Do not include any commentary or disclaimers.
Do not write your promt in any language other than English.

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

    prompt_text = generate_analysis_prompt(
        source=source,
        classification=classification,
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

    analysis = json.loads(content)

    db_analysis = Analysis(
        anl_prm_id=db_prompt.prm_id,

        # Not asset/portfolio-specific yet.
        anl_prt_id=None,
        anl_ast_id=None,

        anl_trigger_type="classification",
        anl_trigger_reason=classification.cls_reason,

        anl_response_text=analysis["anl_response_text"],
        anl_summary=analysis["anl_summary"],
        anl_direction=analysis["anl_direction"],
        anl_market_sentiment=analysis["anl_market_sentiment"],
        anl_confidence=analysis["anl_confidence"],
        anl_risk_level=analysis["anl_risk_level"],
        anl_timeframe=analysis["anl_timeframe"],
    )

    db.add(db_analysis)

    # Need anl_id before creating the relationship row.
    await db.flush()

    db_analysis_source = AnalysisSource(
        ans_anl_id=db_analysis.anl_id,
        ans_src_id=source.src_id,
    )

    db.add(db_analysis_source)

    await db.commit()
    await db.refresh(db_analysis)

    return db_analysis

def generate_analysis_prompt(
    source: DataSource,
    classification: SourceClassification,
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
- Do not provide personalized investment advice.
- Do not recommend that anyone buy, sell, or hold an asset.

Return ONLY valid JSON using EXACTLY this structure:

{{
    "anl_response_text": "string",
    "anl_summary": "string",
    "anl_direction": "negative | neutral | positive | mixed",
    "anl_market_sentiment": "bearish | neutral | bullish | mixed",
    "anl_confidence": 0,
    "anl_risk_level": "low | medium | high",
    "anl_timeframe": "short-term | medium-term | long-term | multiple"
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
