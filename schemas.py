"""Objets JSON communs, utilisés notamment par l'authentification."""

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(examples=["ok"])

class LoginRequest(BaseModel):
    username: str
    password: str
 
 
class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str
 
 
class TokenResponse(BaseModel):
    token: str
    message: str
 
 
class UserResponse(BaseModel):
    user_id: int
    username: str
    role: str
 
