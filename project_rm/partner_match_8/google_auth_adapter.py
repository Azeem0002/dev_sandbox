"""Google identity adapter for partner_match_8."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

try:
    from .models import GoogleIdentity
except ImportError:
    from models import GoogleIdentity


# ============================================
# Google auth adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================
def _get_google_client_id() -> str | None:
    """Return configured Google OAuth client id when production validation needs audience checks."""
    return os.getenv("PARTNER_MATCH_GOOGLE_CLIENT_ID")


def _verify_dev_token(id_token: str) -> GoogleIdentity | None:
    """Allow local MVP testing with `dev:name@example.com` instead of a real Google token."""
    if not id_token.startswith("dev:"):
        return None
    email = id_token.removeprefix("dev:").strip().lower()
    if "@" not in email:
        raise ValueError("Dev Google token must look like dev:user@example.com")
    name = email.split("@", 1)[0].replace(".", " ").title()
    return GoogleIdentity(google_sub=f"dev-{email}", email=email, display_name=name)


def _fetch_google_tokeninfo(id_token: str) -> dict:
    """Ask Google to validate one ID token and return token claims."""
    query = urllib.parse.urlencode({"id_token": id_token})
    with urllib.request.urlopen(f"https://oauth2.googleapis.com/tokeninfo?{query}", timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _verify_google_id_token(id_token: str) -> GoogleIdentity:
    """Verify a Google ID token and return the safe identity fields."""
    dev_identity = _verify_dev_token(id_token)
    if dev_identity is not None:
        return dev_identity

    claims = _fetch_google_tokeninfo(id_token)
    client_id = _get_google_client_id()
    if client_id and claims.get("aud") != client_id:
        raise ValueError("Google token was not issued for this app")
    if claims.get("email_verified") not in {"true", True}:
        raise ValueError("Google email is not verified")

    email = str(claims.get("email") or "").strip().lower()
    google_sub = str(claims.get("sub") or "").strip()
    if not email or not google_sub:
        raise ValueError("Google token is missing identity fields")
    return GoogleIdentity(
        google_sub=google_sub,
        email=email,
        display_name=str(claims.get("name") or email.split("@", 1)[0]).strip(),
        avatar_url=str(claims.get("picture") or "").strip() or None,
    )


# ============================================
# Public adapter API - stable reusable surface
# Responsibility-order adapters are grouped by the job they do, not by install/start/stop lifecycle.
# Read them as: prepare inputs -> call the outside system -> map results back to app-safe data.
# ============================================
def verify_google_id_token(id_token: str) -> GoogleIdentity:
    """Public wrapper for Google ID token verification."""
    return _verify_google_id_token(id_token)
