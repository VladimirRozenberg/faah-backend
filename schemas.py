"""Objets JSON communs, utilisés notamment par l'authentification."""

from typing import Annotated

from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    StringConstraints,
)


# Règles pour le nom d'utilisateur :
# - 3 à 30 caractères
# - lettres minuscules, chiffres, point, tiret et underscore seulement
Username = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=3,
        max_length=30,
        pattern=r"^[a-z0-9._-]+$",
    ),
]


class HealthResponse(BaseModel):
    status: str = Field(examples=["ok"])


class LoginRequest(BaseModel):
    # On laisse volontairement des strings simples ici :
    # un ancien utilisateur ayant le mot de passe "1234"
    # doit encore pouvoir se connecter.
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: Username
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    token: str
    message: str


class UserResponse(BaseModel):
    user_id: int
    username: str
    role: str
    balance: float
