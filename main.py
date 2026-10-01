from fastapi import FastAPI
from sqlalchemy import text
import os

from routers import (
    analyses,
    assets,
    classifications,
    data_sources,
    health,
    live_market,
    orchestrator,
    strategists,
    portfolios,
    signals,
    favorites,
)
import prompt.prompts as prompts
from db import DbSession
from extraction.extract_article import extract_article
from auth import login
from admin import gestion
import logging
from dotenv import load_dotenv
import asyncio
from contextlib import asynccontextmanager
from orchestrator_agent.service import run_orchestrator_service
from portfolio_strategist.service import run_strategist_service

load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# Uvicorn configures its own named loggers before importing this module. Set
# the root level explicitly so FAAH module logs are not left at WARNING.
logging.getLogger().setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

logger = logging.getLogger(__name__)


RUN_ORCHESTRATOR = os.getenv("RUN_ORCHESTRATOR", "false").lower() == "true"
RUN_STRATEGISTS = os.getenv("RUN_STRATEGISTS", "false").lower() == "true"


@asynccontextmanager
async def lifespan(app: FastAPI):
    background_tasks: list[asyncio.Task] = []

    if RUN_ORCHESTRATOR:
        background_tasks.append(
            asyncio.create_task(
                run_orchestrator_service(),
                name="faah-orchestrator",
            )
        )
        logger.info("Started the PostgreSQL-backed orchestrator service")
    else:
        logger.info("Background orchestrator is disabled")

    if RUN_STRATEGISTS:
        background_tasks.append(
            asyncio.create_task(
                run_strategist_service(),
                name="faah-portfolio-strategists",
            )
        )
        logger.info("Started the opportunity and portfolio strategist service")
    else:
        logger.info("Portfolio strategist service is disabled")

    app.state.background_tasks = background_tasks

    try:
        yield
    finally:
        logger.info(
            "Stopping %d background task(s)",
            len(background_tasks),
        )

        for task in background_tasks:
            task.cancel()

        results = await asyncio.gather(
            *background_tasks,
            return_exceptions=True,
        )

        for task, result in zip(background_tasks, results):
            if isinstance(result, Exception) and not isinstance(
                result,
                asyncio.CancelledError,
            ):
                logger.error(
                    "Worker %s stopped with an error: %r",
                    task.get_name(),
                    result,
                )

        logger.info("All background tasks stopped")


# Keep documentation disabled unless a private path is configured.
DOCS_PATH = os.getenv("DOCS_PATH", "").strip().rstrip("/") or None
if DOCS_PATH and (
    not DOCS_PATH.startswith("/")
    or DOCS_PATH in {"/docs", "/redoc", "/openapi.json"}
    or any(char in DOCS_PATH for char in "?#{}")
):
    raise ValueError("DOCS_PATH must be a non-default absolute URL path")

app = FastAPI(
    title="FAAH API",
    description="API backend de l'application FAAH",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=DOCS_PATH,
    redoc_url=None,
    openapi_url=f"{DOCS_PATH}/openapi.json" if DOCS_PATH else None,
    swagger_ui_oauth2_redirect_url=None,
)

app.include_router(health.router)
app.include_router(assets.router)
app.include_router(live_market.router)
app.include_router(portfolios.router)
app.include_router(data_sources.router)
app.include_router(classifications.router)
app.include_router(analyses.router)
app.include_router(signals.router)
app.include_router(orchestrator.router)
app.include_router(strategists.router)
app.include_router(prompts.router, prefix="/prompt")
app.include_router(login.router)
app.include_router(gestion.router)
app.include_router(favorites.router)
 


@app.get("/test-db")
async def test_db(db: DbSession):
    result = await db.execute(text("SELECT * FROM test"))
    rows = result.mappings().all()

    return {
        "connected": True,
        "rows": [dict(row) for row in rows],
    }



@app.get("/test_article_extraction")
async def test_article_extraction(url : str):
    article_content = await extract_article(url)

    if article_content is None:
        return {
            "message": "Failed to extract article content."
            }
    return article_content
"""
SOURCES : https://fastapi.tiangolo.com/ --DOCUMENTATION FASTAPI
        https://docs.docker.com/compose/intro/features-uses/ --DOCUMENTATION DOCKER COMPOSE
"""
