"""Logique métier réservée au super-administrateur (gestion des comptes)."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import models
from schemas import TokenResponse, UserResponse
from auth.authService import UsernameTakenError, UserNotFoundError, auth_service


class SelfLockoutError(Exception):
    """L'admin essaie de se désactiver ou de se retirer son propre rôle admin."""


class AdminService:

    def _to_user_response(self, user: models.User) -> UserResponse:
        return UserResponse(user_id=user.usr_id, username=user.usr_username, role=user.usr_role)

    async def list_users(self, db) -> list[UserResponse]:
        """Retourne tous les utilisateurs, avec leur rôle."""

        query = select(models.User)
        result = await db.execute(query)
        users = result.scalars().all()
        return [self._to_user_response(u) for u in users]

    async def set_active(self, user_id: int, is_active: bool, admin_id: int, db) -> UserResponse:
        """Active ou désactive un compte (suppression logique)."""

        if user_id == admin_id and not is_active:
            raise SelfLockoutError("Tu ne peux pas désactiver ton propre compte.")

        user = await self._get_user_or_raise(user_id, db)
        user.usr_is_active = is_active
        await db.commit()
        await db.refresh(user)
        return self._to_user_response(user)

    async def set_role(self, user_id: int, role: str, admin_id: int, db) -> UserResponse:
        """Change le rôle (employe/admin) d'un utilisateur."""

        if user_id == admin_id and role != "admin":
            raise SelfLockoutError("Tu ne peux pas te retirer ton propre rôle d'administrateur.")

        user = await self._get_user_or_raise(user_id, db)
        user.usr_role = role
        await db.commit()
        await db.refresh(user)
        return self._to_user_response(user)

    async def create_user(self, username: str, email: str, password: str, role: str, db) -> TokenResponse:
        """Crée un utilisateur avec un rôle défini par l'admin (employe ou admin)."""

        clean_username = username.strip().lower()
        clean_email = email.strip().lower()
        hashed_password = auth_service._hash_password(password)

        try:
            new_user = models.User(
                usr_username=clean_username,
                usr_email=clean_email,
                usr_password_hash=hashed_password,
                usr_role=role,
            )
            db.add(new_user)
            await db.flush()
            token = auth_service._create_token(new_user.usr_id, clean_username)
            await db.commit()
        except IntegrityError as error:
            await db.rollback()
            raise UsernameTakenError() from error

        return TokenResponse(token=token, message=f"Compte {clean_username} créé avec le rôle {role}.")

    async def _get_user_or_raise(self, user_id: int, db) -> models.User:
        query = select(models.User).where(models.User.usr_id == user_id)
        result = await db.execute(query)
        user = result.scalar_one_or_none()
        if user is None:
            raise UserNotFoundError()
        return user


admin_service = AdminService()