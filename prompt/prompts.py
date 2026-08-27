from fastapi import APIRouter, Depends, HTTPException,status
from prompt import prompt_text as prompts
from db import DbSession


router = APIRouter(tags=["Prompts"])




@router.get("/classify/{source_id}")
async def classify_source_endpoint(source_id: int, db: DbSession):
    classification = await prompts.classify_source(source_id, db)
    return classification

@router.get("/generate_analysis/{source_id}/{classification_id}")
async def generate_analysis_endpoint(source_id: int, classification_id: int, db: DbSession):
    analysis = await prompts.analyze_source(source_id, classification_id, db)
    return analysis
