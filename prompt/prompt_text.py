import db
from sqlalchemy import select

import json

from models import DataSource, Prompt, SourceClassification
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

    response = await client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[
            {
                "role": "system",
                "content": "You are a financial information classifier.",
            },
            {
                "role": "user",
                "content": prompt_text,
            },
        ],
        max_tokens=300,
        extra_body={
            "thinking": {
                "type": "disabled",
            }
        },
    )

    content = response.choices[0].message.content

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

    return db_classification


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

Return ONLY valid JSON using EXACTLY this structure:

{{
    "cls_category": "string",
    "cls_importance": "low | medium | high",
    "cls_sentiment": "negative | neutral | positive",
    "cls_should_trigger": true,
    "cls_reason": "short explanation"
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

cls_should_trigger:
Set to true when the information is significant enough that another
analysis process should investigate its potential financial impact.
Otherwise set to false.

cls_reason:
Briefly explain why you chose the classification and whether the
information could matter financially.

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