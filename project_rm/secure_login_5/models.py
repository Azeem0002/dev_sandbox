from __future__ import annotations
"""Core models for secure_login_5."""

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel


class RegisterUserDTO(BaseModel):
    """HTTP input for account registration."""
    email: str
    password: str


class LoginUserDTO(BaseModel):
    """HTTP input for account login."""
    email: str
    password: str


class GoogleLoginDTO(BaseModel):
    """HTTP input for Google login."""
    id_token: str


class TokenDTO(BaseModel):
    """HTTP output containing a bearer access token."""
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int


class UserDTO(BaseModel):
    """HTTP-safe user output without password hash."""
    id: str
    email: str
    created_at: datetime


@dataclass
class User:
    """Internal persisted user model."""
    id: str
    email: str
    password_hash: str
    created_at: datetime
    google_sub: str | None = None


@dataclass(frozen=True)
class GoogleIdentity:
    """Verified Google identity returned by the auth adapter."""
    google_sub: str
    email: str
    display_name: str
    avatar_url: str | None = None


@dataclass
class AuthSession:
    """Server-side session record tied to one JWT token id."""
    id: str
    user_id: str
    token_id: str
    expires_at: datetime
    revoked_at: datetime | None = None


@dataclass
class AuthResult:
    """Application result after successful register/login."""
    user: User
    session: AuthSession
    access_token: str
    expires_in_seconds: int
