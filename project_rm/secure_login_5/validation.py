"""Validation/parsing helpers for secure_login_5."""

import re

try:
    from .models import LoginUserDTO, RegisterUserDTO
except ImportError:
    from models import LoginUserDTO, RegisterUserDTO


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(value: str) -> str:
    """Normalize and validate an email address."""
    cleaned = value.strip().casefold() if isinstance(value, str) else ""
    if not EMAIL_PATTERN.match(cleaned):
        raise ValueError("Use a valid email address")
    return cleaned


def validate_password(value: str) -> str:
    """Validate MVP password strength before hashing."""
    if not isinstance(value, str) or len(value) < 8:
        raise ValueError("Password must be at least 8 characters")
    if not any(char.isalpha() for char in value) or not any(char.isdigit() for char in value):
        raise ValueError("Password must include letters and numbers")
    return value


def build_register_user_request(payload: RegisterUserDTO) -> RegisterUserDTO:
    """Build clean registration input from raw API payload."""
    return RegisterUserDTO(email=normalize_email(payload.email), password=validate_password(payload.password))


def build_login_user_request(payload: LoginUserDTO) -> LoginUserDTO:
    """Build clean login input from raw API payload."""
    return LoginUserDTO(email=normalize_email(payload.email), password=payload.password)
