"""Prompt templates for source classification and financial analysis."""

from models import DataSource, Niche, SourceClassification
from prompt.niche_assignment import format_niches_by_category


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
The information in this article is fresh meaning it is not old news (published within the last 2 hours)

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
