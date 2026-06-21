"""AI agent adapter for group chat.

MVP uses a local deterministic assistant so the app works without paid API keys.
Replace this adapter later with OpenAI or another provider without changing group logic.
"""

from __future__ import annotations

try:
    from .models import ChatMessage, PartnerGroup
except ImportError:
    from models import ChatMessage, PartnerGroup


# ============================================
# AI adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================
def _build_group_agent_reply(group: PartnerGroup, recent_messages: list[ChatMessage]) -> str:
    """Build a practical group-assistant reply from recent chat context."""
    last_user_message = next((message.body for message in reversed(recent_messages) if message.sender_type.value == "user"), "")
    return (
        f"AI teammate for {group.name}: turn this into one concrete next step. "
        f"Latest point: {last_user_message[:180] or 'No recent context yet.'}"
    )


# ============================================
# Public adapter API - stable reusable surface
# ============================================
def build_group_agent_reply(group: PartnerGroup, recent_messages: list[ChatMessage]) -> str:
    """Public wrapper for generating an AI teammate response."""
    return _build_group_agent_reply(group, recent_messages)
