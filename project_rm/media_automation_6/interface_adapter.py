"""Frontend interface contract adapter for media_automation_6.

This module does not render a GUI. It exposes the stable backend contract that
any replaceable frontend can use: web app, mobile app, desktop app, or a future
admin dashboard.
"""

PROJECT_NAME = "media_automation_6"


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
        "frontend_rule": "Build any GUI you want; do not duplicate backend validation, scheduling, or publishing rules in the GUI.",
        "base_url": "Set per environment, for example http://127.0.0.1:8000 locally.",
        "auth": {
            "type": "Bearer JWT",
            "header": "Authorization: Bearer <access_token>",
            "token_source": "secure_login_5",
        },
        "endpoints": [
            {"method": "GET", "path": "/health", "auth_required": False, "purpose": "Check backend liveness."},
            {"method": "POST", "path": "/generate", "auth_required": True, "purpose": "Generate one post draft."},
            {"method": "POST", "path": "/posts", "auth_required": True, "purpose": "Generate and schedule one post."},
            {"method": "GET", "path": "/posts", "auth_required": True, "purpose": "List recent saved posts."},
            {"method": "POST", "path": "/posts/{post_id}/publish", "auth_required": True, "purpose": "Publish one post now."},
            {"method": "POST", "path": "/publish-due", "auth_required": True, "purpose": "Publish all due posts."},
            {"method": "POST", "path": "/automation/start", "auth_required": True, "purpose": "Start background automation checks."},
            {"method": "POST", "path": "/automation/stop", "auth_required": True, "purpose": "Stop background automation checks."},
            {"method": "GET", "path": "/automation/status", "auth_required": True, "purpose": "Read automation status."},
        ],
        "frontend_must_send": ["JSON request bodies", "Content-Type: application/json", "Authorization header on protected routes"],
        "frontend_should_handle": ["400 validation errors", "401 login/session errors", "scheduled/publishing status refresh"],
    }
