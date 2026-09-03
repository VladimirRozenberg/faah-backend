"""Routes HTTP réservées au super-administrateur."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from auth.login import CurrentUser
from auth.authService import UsernameTakenError, UserNotFoundError
from .adminService import SelfLockoutError, admin_service

from schemas import TokenResponse, UserResponse
from db import DbSession

# Toutes les routes de ce fichier commencent par /admin et sont regroupées
# sous le titre « Administration » dans la documentation Swagger.
router = APIRouter(prefix="/admin", tags=["Administration"])


def raise_http_error(error: Exception) -> None:
    """Convertit les erreurs du service en réponses HTTP compréhensibles."""

    if isinstance(error, UserNotFoundError):
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.") from error
    if isinstance(error, UsernameTakenError):
        raise HTTPException(status_code=409, detail="Ce nom d'utilisateur ou cet email est déjà pris.") from error
    if isinstance(error, SelfLockoutError):
        raise HTTPException(status_code=400, detail=str(error)) from error
    raise error


def get_current_admin(user: CurrentUser) -> UserResponse:
    """Exige un utilisateur authentifié ET avec le rôle admin."""

    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Accès réservé au super-administrateur.")
    return user


AdminUser = Depends(get_current_admin)


class StatutUpdate(BaseModel):
    is_active: bool


class RoleUpdate(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def role_valide(cls, v):
        if v not in ("employe", "admin"):
            raise ValueError("Le rôle doit être 'employe' ou 'admin'.")
        return v


class AdminCreateUserRequest(BaseModel):
    username: str
    email: str
    password: str
    role: str = "employe"

    @field_validator("role")
    @classmethod
    def role_valide(cls, v):
        if v not in ("employe", "admin"):
            raise ValueError("Le rôle doit être 'employe' ou 'admin'.")
        return v


@router.get("/utilisateurs", response_model=list[UserResponse])
async def liste_utilisateurs(db: DbSession, admin: UserResponse = AdminUser) -> list[UserResponse]:
    """Retourne la liste de tous les utilisateurs."""

    return await admin_service.list_users(db)


@router.put("/utilisateurs/{user_id}/statut", response_model=UserResponse)
async def modifier_statut_utilisateur(
    user_id: int, donnees: StatutUpdate, db: DbSession, admin: UserResponse = AdminUser
) -> UserResponse:
    """Active ou désactive un compte utilisateur (suppression logique)."""

    try:
        return await admin_service.set_active(user_id, donnees.is_active, admin.user_id, db)
    except Exception as error:
        raise_http_error(error)
        raise


@router.put("/utilisateurs/{user_id}/role", response_model=UserResponse)
async def modifier_role_utilisateur(
    user_id: int, donnees: RoleUpdate, db: DbSession, admin: UserResponse = AdminUser
) -> UserResponse:
    """Change le rôle (employe/admin) d'un utilisateur."""

    try:
        return await admin_service.set_role(user_id, donnees.role, admin.user_id, db)
    except Exception as error:
        raise_http_error(error)
        raise


@router.post("/utilisateurs", response_model=TokenResponse)
async def creer_utilisateur(
    donnees: AdminCreateUserRequest, db: DbSession, admin: UserResponse = AdminUser
) -> TokenResponse:
    """Crée un nouveau compte utilisateur avec un rôle choisi par l'admin."""

    try:
        return await admin_service.create_user(
            donnees.username, donnees.email, donnees.password, donnees.role, db
        )
    except Exception as error:
        raise_http_error(error)
        raise