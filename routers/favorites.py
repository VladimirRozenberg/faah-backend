"""Favoris persistants, toujours limités à l'utilisateur du token."""
from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from auth.login import CurrentUser
from db import DbSession
from models import Asset, Favorite

router = APIRouter(prefix="/api/favorites", tags=["Favorites"])


@router.get("")
async def list_favorites(user: CurrentUser, db: DbSession) -> dict:
    ids = await db.scalars(select(Favorite.fav_ast_id).where(
        Favorite.fav_usr_id == user.user_id).order_by(Favorite.fav_ast_id))
    return {"asset_ids": list(ids)}


@router.put("/{asset_id}", status_code=204)
async def add_favorite(asset_id: int, user: CurrentUser, db: DbSession) -> Response:
    if await db.get(Asset, asset_id) is None:
        raise HTTPException(status_code=404, detail="Actif introuvable.")
    await db.execute(insert(Favorite).values(
        fav_usr_id=user.user_id, fav_ast_id=asset_id
    ).on_conflict_do_nothing(index_elements=["fav_usr_id", "fav_ast_id"]))
    await db.commit()
    return Response(status_code=204)


@router.delete("/{asset_id}", status_code=204)
async def remove_favorite(asset_id: int, user: CurrentUser, db: DbSession) -> Response:
    await db.execute(delete(Favorite).where(
        Favorite.fav_usr_id == user.user_id, Favorite.fav_ast_id == asset_id))
    await db.commit()
    return Response(status_code=204)
