"""Logique métier de l'authentification (hash, vérification, tokens)."""

import os
import time

import bcrypt
import jwt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import models
from schemas import TokenResponse, UserResponse

TOKEN_HEX_KEY = os.getenv("hex_code")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


# ---------------------------------------------------------------------
# Erreurs métier — converties en réponses HTTP dans login.py (raise_http_error)
# ---------------------------------------------------------------------

class InvalidCredentialsError(Exception):
    """Le nom d'utilisateur n'existe pas, ou le mot de passe ne correspond pas."""


class UsernameTakenError(Exception):
    """Ce nom d'utilisateur (ou cet email) est déjà utilisé par un autre compte."""


class TokenError(Exception):
    """Le token est invalide, expiré, ou mal formé."""


class UserNotFoundError(Exception):
    """Le token est valide, mais l'utilisateur associé n'existe plus."""


# ---------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------

class AuthService:

    def _hash_password(self, password: str) -> str:
        password_bytes = password.encode("utf-8")
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password_bytes, salt).decode()

    def _verify_password(self, password_text: str, hashed_password: str) -> bool:
        return bcrypt.checkpw(password_text.encode("utf-8"), hashed_password.encode("utf-8"))

    def _create_token(self, user_id: int, username: str) -> str:
        expire_timestamp = int(time.time()) + (ACCESS_TOKEN_EXPIRE_MINUTES * 60)
        payload = {
            "sub": str(user_id),
            "username": username,
            "exp": expire_timestamp,
        }
        return jwt.encode(payload, TOKEN_HEX_KEY, algorithm=ALGORITHM)

    def _to_user_response(self, user: models.User) -> UserResponse:
        return UserResponse(user_id=user.usr_id, username=user.usr_username, role=user.usr_role)

    async def login(self, username: str, password: str, db) -> TokenResponse:
        """Vérifie les identifiants et retourne un token d'accès."""

        query = select(models.User).where(models.User.usr_username == username.lower())
        result = await db.execute(query)
        user = result.scalar_one_or_none()

        if user is None or not self._verify_password(password, user.usr_password_hash):
            raise InvalidCredentialsError()

        if not user.usr_is_active:
            raise InvalidCredentialsError()

        token = self._create_token(user.usr_id, user.usr_username)
        return TokenResponse(token=token, message=f"Welcome back {user.usr_username}!")

    async def register(self, username: str, email: str, password: str, db) -> TokenResponse:
        """Crée un nouveau compte utilisateur et retourne un token d'accès."""

        clean_username = username.strip().lower()
        clean_email = email.strip().lower()
        hashed_password = self._hash_password(password)

        try:
            new_user = models.User(
                usr_username=clean_username,
                usr_email=clean_email,
                usr_password_hash=hashed_password,
            )
            db.add(new_user)
            await db.flush()  # pour récupérer new_user.usr_id avant le commit

            token = self._create_token(new_user.usr_id, clean_username)
            await db.commit()
        except IntegrityError as error:
            await db.rollback()
            raise UsernameTakenError() from error

        return TokenResponse(token=token, message=f"Welcome {clean_username} to FAAH!")

    async def get_user_from_token(self, token: str, db) -> UserResponse:
        """Décode le token et retourne l'utilisateur correspondant."""

        try:
            payload = jwt.decode(token, TOKEN_HEX_KEY, algorithms=[ALGORITHM])
        except jwt.ExpiredSignatureError as error:
            raise TokenError("Token expiré, merci de te reconnecter.") from error
        except jwt.InvalidTokenError as error:
            raise TokenError("Token invalide.") from error

        user_id = payload.get("sub")
        if user_id is None:
            raise TokenError("Token mal formé.")

        query = select(models.User).where(models.User.usr_id == int(user_id))
        result = await db.execute(query)
        user = result.scalar_one_or_none()

        if user is None or not user.usr_is_active:
            raise UserNotFoundError()

        return self._to_user_response(user)


auth_service = AuthService()