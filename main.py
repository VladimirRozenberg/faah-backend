from fastapi import FastAPI
from sqlalchemy import text, select

from routers import assets, health
import prompt.prompts as prompts
from db import DbSession

app = FastAPI(
    title="FAAH API",
    description="API backend de l'application FAAH",
    version="0.1.0",
)

app.include_router(health.router)
app.include_router(assets.router)
app.include_router(prompts.router, prefix="/prompt")



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