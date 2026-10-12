"""Routes HTTP réservées au super-administrateur."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field, field_validator
from decimal import Decimal
from portfolio.repository import (
    deposit_cash,
    read_user_available_cash,
    read_user_asset_value,
    read_user_transactions,
    read_user_deposits,
)
from portfolio.schemas import (
    UserAvailableCashResponse,
    UserAssetValueResponse,
    UserTransactionListResponse,
    UserDepositListResponse,
)

from auth.login import CurrentUser
from auth.authService import UsernameTakenError, UserNotFoundError
from .adminService import SelfLockoutError, admin_service

from schemas import TokenResponse, UserResponse, Username, validate_password_length
from db import DbSession

# Toutes les routes de ce fichier commencent par /admin et sont regroupées
# sous le titre « Administration » dans la documentation Swagger.
router = APIRouter(prefix="/admin", tags=["Administration"])


def raise_http_error(error: Exception) -> None:
    """Convertit les erreurs du service en réponses HTTP compréhensibles."""

    if isinstance(error, UserNotFoundError):
        raise HTTPException(status_code=404, detail="User not found.") from error
    if isinstance(error, UsernameTakenError):
        raise HTTPException(status_code=409, detail="This username or email is already in use.") from error
    if isinstance(error, SelfLockoutError):
        raise HTTPException(status_code=400, detail=str(error)) from error
    raise error


def get_current_admin(user: CurrentUser) -> UserResponse:
    """Exige un utilisateur authentifié ET avec le rôle admin."""

    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator access is required.")
    return user


AdminUser = Depends(get_current_admin)


@router.get("/users/{user_id}/available-cash", response_model=UserAvailableCashResponse)
async def get_user_available_cash(
    user_id: int, db: DbSession, admin: UserResponse = AdminUser,
) -> UserAvailableCashResponse:
    """Return the selected account's available simulated USD cash."""
    try:
        return await read_user_available_cash(db, user_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/users/{user_id}/asset-value", response_model=UserAssetValueResponse)
async def get_user_asset_value(
    user_id: int, db: DbSession, admin: UserResponse = AdminUser,
) -> UserAssetValueResponse:
    """Return the USD value of active holdings across the selected account's portfolios."""
    try:
        return await read_user_asset_value(db, user_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/users/{user_id}/transactions", response_model=UserTransactionListResponse)
async def get_user_transactions(
    user_id: int, db: DbSession, admin: UserResponse = AdminUser,
    page: int = Query(default=1, ge=1),
) -> UserTransactionListResponse:
    """Return ten transactions per page across the selected account's portfolios."""
    try:
        return await read_user_transactions(db, user_id, page)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/users/{user_id}/deposits", response_model=UserDepositListResponse)
async def get_user_deposits(
    user_id: int, db: DbSession, admin: UserResponse = AdminUser,
    page: int = Query(default=1, ge=1),
) -> UserDepositListResponse:
    """Return ten deposits per page for the selected account."""
    try:
        return await read_user_deposits(db, user_id, page)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


class StatutUpdate(BaseModel):
    is_active: bool


class RoleUpdate(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def role_valide(cls, v):
        if v not in ("employe", "admin"):
            raise ValueError("The role must be 'employe' or 'admin'.")
        return v


class AdminCreateUserRequest(BaseModel):
    username: Username
    email: EmailStr
    password: str
    role: str = "employe"

    @field_validator("role")
    @classmethod
    def role_valide(cls, value: str) -> str:
        if value not in ("employe", "admin"):
            raise ValueError("The role must be 'employe' or 'admin'.")
        return value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return validate_password_length(value)


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

class DepositRequest(BaseModel):
    amount: Decimal = Field(gt=0, le=1000000000, max_digits=12, decimal_places=2, allow_inf_nan=False)


@router.post("/utilisateurs/{user_id}/deposit")
async def recharge_compte(user_id: int, data: DepositRequest, db: DbSession, admin: UserResponse = AdminUser):
    try:
        return await deposit_cash(db, user_id, data.amount, admin_user_id=admin.user_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
