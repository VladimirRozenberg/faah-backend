from fastapi import FastAPI
from sqlalchemy import text, select

from db import DbSession

app = FastAPI()


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