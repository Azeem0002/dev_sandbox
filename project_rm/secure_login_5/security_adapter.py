"""Security adapter for password hashing and JWT handling."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


# ============================================
# Security adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================
def _get_jwt_secret() -> bytes:
    """Return JWT signing secret from env, with dev fallback only for local MVP."""
    # Production must set SECURE_LOGIN_JWT_SECRET.
    # The fallback exists only so the learning project runs locally without setup.
    return os.getenv("SECURE_LOGIN_JWT_SECRET", "dev-only-change-me").encode("utf-8")


def _get_access_token_seconds() -> int:
    """Return token lifetime in seconds."""
    return int(os.getenv("SECURE_LOGIN_ACCESS_TOKEN_SECONDS", "3600"))


def _get_password_hasher() -> PasswordHasher:
    """Return the production password hasher used for stored user passwords."""
    # Argon2id is the practical launch default for password hashing.
    # The adapter hides the library so application code still calls hash_password()/verify_password().
    return PasswordHasher()


def _b64url_encode(data: bytes) -> str:
    """Encode bytes using JWT-compatible base64url without padding."""
    # JWT segments use URL-safe base64 and strip "=" padding.
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    """Decode JWT-compatible base64url text."""
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _sign(message: str) -> str:
    """Return HMAC signature for JWT header.payload."""
    return _b64url_encode(hmac.new(_get_jwt_secret(), message.encode("utf-8"), hashlib.sha256).digest())


def _hash_password(password: str) -> str:
    """Hash password with Argon2id for launch-ready password storage."""
    return _get_password_hasher().hash(password)


def _verify_password(password: str, password_hash: str) -> bool:
    """Verify raw password against stored Argon2id hash."""
    try:
        return _get_password_hasher().verify(password_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError, TypeError):
        return False


def _create_access_token(*, user_id: str, token_id: str, expires_in_seconds: int) -> str:
    """Create a signed compact JWT."""
    now = datetime.now(timezone.utc)
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": user_id,
        "jti": token_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in_seconds)).timestamp()),
    }
    # Compact JSON avoids unnecessary spaces in the token.
    signing_input = f"{_b64url_encode(json.dumps(header, separators=(',', ':')).encode())}.{_b64url_encode(json.dumps(payload, separators=(',', ':')).encode())}"
    return f"{signing_input}.{_sign(signing_input)}"


def _decode_access_token(token: str) -> dict:
    """Verify and decode a signed compact JWT."""
    try:
        header_text, payload_text, signature = token.split(".")
    except ValueError as error:
        raise ValueError("Invalid token") from error

    signing_input = f"{header_text}.{payload_text}"
    if not hmac.compare_digest(_sign(signing_input), signature):
        raise ValueError("Invalid token signature")

    payload = json.loads(_b64url_decode(payload_text))
    if int(payload.get("exp", 0)) < int(datetime.now(timezone.utc).timestamp()):
        raise ValueError("Token expired")
    return payload


# ============================================
# Public adapter API - stable reusable surface
# ============================================
def hash_password(password: str) -> str:
    """Public wrapper for password hashing."""
    return _hash_password(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Public wrapper for password verification."""
    return _verify_password(password, password_hash)


def create_token_id() -> str:
    """Create a random JWT/session id."""
    return secrets.token_urlsafe(24)


def create_access_token(*, user_id: str, token_id: str, expires_in_seconds: int) -> str:
    """Public wrapper for JWT creation."""
    return _create_access_token(user_id=user_id, token_id=token_id, expires_in_seconds=expires_in_seconds)


def decode_access_token(token: str) -> dict:
    """Public wrapper for JWT verification/decoding."""
    return _decode_access_token(token)


def get_access_token_seconds() -> int:
    """Public wrapper for configured access-token lifetime."""
    return _get_access_token_seconds()
