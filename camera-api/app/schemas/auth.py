from pydantic import Field

from app.schemas.base import CamelModel


class LoginRequest(CamelModel):
    login: str
    password: str


class LoginResponse(CamelModel):
    token: str
    role: str  # "super-admin" | "admin" — always derived server-side, never trusted from the client
    user_name: str


class ForgotPasswordIn(CamelModel):
    login: str


class ResetPasswordIn(CamelModel):
    token: str
    new_password: str = Field(min_length=8)
