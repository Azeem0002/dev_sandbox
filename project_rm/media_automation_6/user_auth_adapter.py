"""User auth guard adapter for API endpoints that need logged-in users."""

from __future__ import annotations

try:
    from secure_login_5.application import get_current_user
except ImportError:
    get_current_user = None


# ============================================
# User auth adapter - reusable mental map
# ============================================
# This adapter is intentionally small. Product APIs call it at the boundary
# before running paid/user-owned actions. It delegates identity/session checks
# to secure_login_5 so every micro-SaaS does not grow a different login system.
# Keep this file line-for-line synchronized across projects that reuse it.

# ============================================
# Shared private skeleton - start reading here
# ============================================
def _extract_bearer_token(authorization: str | None) -> str:
    """Extract the raw JWT from `Authorization: Bearer <token>`."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ValueError("Log in first and send Authorization: Bearer <token>")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise ValueError("Bearer token is empty")
    return token


def _require_authenticated_user(authorization: str | None) -> dict:
    """Validate one bearer token through secure_login_5 and return safe user data."""
    if get_current_user is None:
        raise ValueError("Shared secure_login_5 auth app is not available")
    user = get_current_user(_extract_bearer_token(authorization))
    return user.model_dump()


# ============================================
# Public adapter API - stable reusable surface
# Responsibility-order adapters are grouped by the job they do, not by install/start/stop lifecycle.
# Read them as: prepare inputs -> call the outside system -> map results back to app-safe data.
# ============================================
def require_authenticated_user(authorization: str | None) -> dict:
    """Public wrapper used by API routes before protected work starts."""
    return _require_authenticated_user(authorization)
