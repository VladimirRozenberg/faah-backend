"""Objets JSON communs, utilisés notamment par l'authentification."""

from typing import Annotated

from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
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
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if not any(char.islower() for char in value):
            raise ValueError(
                "Le mot de passe doit contenir au moins une minuscule."
            )

        if not any(char.isupper() for char in value):
            raise ValueError(
                "Le mot de passe doit contenir au moins une majuscule."
            )

        if not any(char.isdigit() for char in value):
            raise ValueError(
                "Le mot de passe doit contenir au moins un chiffre."
            )

        if not any(not char.isalnum() for char in value):
            raise ValueError(
                "Le mot de passe doit contenir au moins un caractère spécial."
            )

        return value


class TokenResponse(BaseModel):
    token: str
    message: str


class UserResponse(BaseModel):
    user_id: int
    username: str
    role: str
    balance: float
