from fastapi import FastAPI
from sqlalchemy import text, select

from routers import assets, health, live_market
import prompt.prompts as prompts
from prompt import prompt_text
from db import DbSession
import feedparser
from ingestion import rss
from models import DataSource
from extraction.extract_article import extract_article
from workers import workers

app = FastAPI(
    title="FAAH API",
    description="API backend de l'application FAAH",
    version="0.1.0",
)

app.include_router(health.router)
app.include_router(assets.router)
app.include_router(live_market.router)
app.include_router(prompts.router, prefix="/prompt")
app.include_router(workers.router)


@app.get("/test-db")
async def test_db(db: DbSession):
    result = await db.execute(text("SELECT * FROM test"))
    rows = result.mappings().all()

    return {
        "connected": True,
        "rows": [dict(row) for row in rows],
    }

@app.get("/test_db_orm")
async def test_db_orm(db: DbSession):
    result = await db.execute(select(Test))
    rows = result.scalars().all()

    return rows


RSS_URL = "https://www.investing.com/rss/news_25.rss"



@app.get("/ingest-rss")
async def ingest_rss(db: DbSession):

    news = await rss.ingest_investing_stock_news(db)

    if not news:
        return {
            "message": "No new articles found."
        }

    result = await db.execute(
        select(DataSource).where(
            DataSource.src_id.in_(news)
        )
    )

    new_sources = result.scalars().all()

    return {
        "new_count": len(new_sources),

        "articles": [
            {
                "id": source.src_id,
                "title": source.src_title,
                "url": source.src_original_url,
                "content": source.src_content,
                "published_at": source.src_published_at,
            }
            for source in new_sources
        ]
    }


@app.get("/test-rss-analysis")
async def test_rss_analysis(db: DbSession):

    news = await rss.ingest_investing_stock_news(db)

    if not news:
        return {
            "message": "No new articles found."
        }

    results = []

    for source_id in news:

        classification, analysis = await prompt_text.classify_source(
            source_id,
            db,
        )

        results.append(
            {
                "source_id": source_id,
                "category": classification.cls_category,
                "importance": classification.cls_importance,
                "sentiment": classification.cls_sentiment,
                "should_trigger": classification.cls_should_trigger,
                "reason": classification.cls_reason,
                "analysis": (
                    {
                        "summary": analysis.anl_summary,
                        "direction": analysis.anl_direction,
                        "market_sentiment": analysis.anl_market_sentiment,
                        "confidence": analysis.anl_confidence,
                        "risk": analysis.anl_risk_level,
                        "timeframe": analysis.anl_timeframe,
                    }
                    if classification.cls_should_trigger
                    else None
                ),
            }
        )

    return {
        "processed": len(results),
        "results": results,
    }

@app.get("/test_article_extraction")
async def test_article_extraction(url : str):
    article_content = await extract_article(url)

    if article_content is None:
        return {
            "message": "Failed to extract article content."
            }
    return article_content
