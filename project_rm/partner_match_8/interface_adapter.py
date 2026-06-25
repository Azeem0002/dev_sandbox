"""Frontend interface contract adapter for partner_match_8.

This module does not render a GUI. It exposes the stable backend contract that
any replaceable frontend can use: web app, mobile app, desktop app, or a future
admin dashboard.
"""

PROJECT_NAME = "partner_match_8"


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
        "frontend_rule": "Build any GUI you want; do not duplicate backend safety, location, group, feed, or matching rules in the GUI.",
        "base_url": "Set per environment, for example http://127.0.0.1:8000 locally.",
        "auth": {
            "type": "Bearer JWT",
            "header": "Authorization: Bearer <access_token>",
            "login_routes": ["POST /auth/google"],
        },
        "endpoint_groups": [
            {"group": "account", "paths": ["/auth/google", "/me", "/me/username", "/me/profile", "/me/location"]},
            {"group": "discovery", "paths": ["/partners/nearby", "/profiles/{user_id}", "/profile-visits"]},
            {"group": "social", "paths": ["/feed", "/posts", "/posts/{post_id}/likes", "/posts/{post_id}/comments"]},
            {"group": "groups", "paths": ["/groups", "/groups/{group_id}/messages", "/groups/{group_id}/invites"]},
            {"group": "safety", "paths": ["/reports", "/blocks"]},
            {"group": "notifications", "paths": ["/notifications", "/partner-requests"]},
        ],
        "frontend_must_send": ["JSON request bodies", "Content-Type: application/json", "Authorization header on protected routes", "location permission before nearby discovery"],
        "frontend_should_handle": ["400 validation errors", "401 login/session errors", "location permission denied", "empty feed/nearby states", "report/block flows"],
    }
