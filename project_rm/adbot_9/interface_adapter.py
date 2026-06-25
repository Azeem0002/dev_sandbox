"""Frontend interface contract adapter for adbot_9.

This module does not render a GUI. It exposes the stable backend contract that
any replaceable frontend can use: web app, mobile app, desktop app, or a future
admin dashboard.
"""

PROJECT_NAME = "adbot_9"


# ============================================
# Interface adapter - reusable frontend contract
# ============================================
# Frontend handoff mental model:
# 1. The GUI owns screens, buttons, local form state, and visual feedback.
# 2. The backend owns validation, authentication, persistence, and business rules.
# 3. The API boundary exposes HTTP routes; this adapter documents those routes in
#    a machine-readable shape for frontend developers.
# 4. Replace the GUI freely as long as it keeps calling this contract.


# ============================================
# Public adapter API - stable reusable surface
# ============================================
def get_frontend_contract() -> dict:
    """Return the API contract a frontend developer needs to connect a GUI."""
    return {
        "project": PROJECT_NAME,
        "frontend_rule": "Build any GUI you want; do not duplicate backend validation, demand scoring, or campaign-planning rules in the GUI.",
        "base_url": "Set per environment, for example http://127.0.0.1:8000 locally.",
        "auth": {
            "type": "Bearer JWT",
            "header": "Authorization: Bearer <access_token>",
            "token_source": "secure_login_5",
        },
        "endpoints": [
            {"method": "GET", "path": "/health", "auth_required": False, "purpose": "Check backend liveness."},
            {"method": "POST", "path": "/campaigns/recommend", "auth_required": True, "purpose": "Recommend target locations, demand signals, and ad copy."},
            {"method": "GET", "path": "/campaigns/history", "auth_required": True, "purpose": "List recent saved campaign plans."},
            {"method": "GET", "path": "/campaigns/{plan_id}/export", "auth_required": True, "purpose": "Export copyable campaign notes."},
        ],
        "frontend_must_send": ["JSON request bodies", "Content-Type: application/json", "Authorization header on protected routes"],
        "frontend_should_handle": ["400 validation errors", "401 login/session errors", "manual ad-platform review before launch"],
    }
