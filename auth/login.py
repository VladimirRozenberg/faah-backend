"""Routes HTTP liées à l'authentification et au compte utilisateur."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .authService import (
    InvalidCredentialsError,
    TokenError,
    UsernameTakenError,
    UserNotFoundError,
    auth_service,
)

from schemas import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

from db import DbSession

# Toutes les routes de ce fichier commencent par /auth et sont regroupées
# sous le titre « Authentification » dans la documentation Swagger.
router = APIRouter(prefix="/auth", tags=["Authentification"])

security_scheme = HTTPBearer()


def raise_http_error(error: Exception) -> None:
    """Convertit les erreurs du service en réponses HTTP compréhensibles."""

    if isinstance(error, InvalidCredentialsError):
        raise HTTPException(status_code=401, detail="Nom d'utilisateur ou mot de passe incorrect.") from error
    if isinstance(error, UsernameTakenError):
        raise HTTPException(status_code=409, detail="Ce nom d'utilisateur ou cet email est déjà pris.") from error
    if isinstance(error, TokenError):
        raise HTTPException(status_code=401, detail=str(error)) from error
    if isinstance(error, UserNotFoundError):
        raise HTTPException(status_code=401, detail="Utilisateur introuvable.") from error
    raise error


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    db: DbSession,
) -> UserResponse:
    """Vérifie le token et retourne l'utilisateur correspondant."""

    try:
        return await auth_service.get_user_from_token(credentials.credentials, db)
    except Exception as error:
        raise_http_error(error)
        raise


CurrentUser = Annotated[UserResponse, Depends(get_current_user)]


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, db: DbSession) -> TokenResponse:
    """Vérifie les identifiants et retourne un token d'accès."""

    try:
        return await auth_service.login(data.username, data.password, db)
    except Exception as error:
        raise_http_error(error)
        raise  # Cette ligne aide uniquement l'analyse statique de Python.


@router.post("/user_create", response_model=TokenResponse)
async def create_user(data: RegisterRequest, db: DbSession) -> TokenResponse:
    """Crée un nouveau compte utilisateur et retourne un token d'accès."""

    try:
        return await auth_service.register(data.username, data.email, data.password, db)
    except Exception as error:
        raise_http_error(error)
        raise


@router.get("/me", response_model=UserResponse)
async def read_current_user(user: CurrentUser) -> UserResponse:
    """Retourne les informations de l'utilisateur actuellement connecté."""

    return user