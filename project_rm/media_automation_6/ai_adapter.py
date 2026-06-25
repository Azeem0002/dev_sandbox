"""AI/content adapter for media_automation_6."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

try:
    from .models import ContentIdeaRequest, SocialPlatform, Tone
except ImportError:
    from models import ContentIdeaRequest, SocialPlatform, Tone


# ============================================
# AI adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================
def _platform_character_limit(platform: SocialPlatform) -> int:
    """Return a practical draft length limit for one platform."""
    return 260 if platform == SocialPlatform.X else 1200 if platform == SocialPlatform.LINKEDIN else 900


def _tone_opening(tone: Tone) -> str:
    """Return a first-line style cue for local content generation."""
    return {
        Tone.PRACTICAL: "Here is the practical truth:",
        Tone.BOLD: "Most people are missing this:",
        Tone.FRIENDLY: "A useful reminder:",
        Tone.EDUCATIONAL: "Quick lesson:",
    }[tone]


def _build_content_template(request: ContentIdeaRequest) -> str:
    """Build one platform-ready draft from clean content input."""
    return (
        f"{_tone_opening(request.tone)} {request.topic}.\n\n"
        f"For {request.audience}, the goal is simple: {request.goal}.\n\n"
        "Use this checklist:\n"
        "1. State the painful problem clearly.\n"
        "2. Show the practical fix.\n"
        "3. Give one proof point or example.\n"
        "4. End with one direct question.\n\n"
        f"What is your next move on {request.topic}?"
    )


def _trim_for_platform(content: str, platform: SocialPlatform) -> str:
    """Trim generated content to a safe platform length."""
    limit = _platform_character_limit(platform)
    return content if len(content) <= limit else content[: limit - 3].rstrip() + "..."


def _score_posting_hour(platform: SocialPlatform, scheduled_at: datetime) -> float:
    """Score a posting time using a small local heuristic."""
    # Free MVP heuristic: LinkedIn favors workday mornings; consumer platforms favor evenings.
    local = scheduled_at.astimezone()
    weekday_bonus = 12.0 if local.weekday() < 5 else 4.0
    if platform == SocialPlatform.LINKEDIN:
        base = 80.0 if 8 <= local.hour <= 11 else 45.0
    elif platform == SocialPlatform.X:
        base = 75.0 if 7 <= local.hour <= 10 or 17 <= local.hour <= 20 else 50.0
    else:
        base = 78.0 if 18 <= local.hour <= 21 else 52.0
    return min(100.0, base + weekday_bonus)


def _suggest_next_post_time(platform: SocialPlatform, now: datetime) -> tuple[datetime, float]:
    """Suggest the next reasonable posting time and return its score."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    preferred_hour = 9 if platform == SocialPlatform.LINKEDIN else 18
    candidate = now.replace(hour=preferred_hour, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate = candidate + timedelta(days=1)
    if platform == SocialPlatform.LINKEDIN:
        while candidate.weekday() >= 5:
            candidate = candidate + timedelta(days=1)
    return candidate.astimezone(timezone.utc), _score_posting_hour(platform, candidate)


# ============================================
# Public adapter API - stable reusable surface
# Responsibility-order adapters are grouped by the job they do, not by install/start/stop lifecycle.
# Read them as: prepare inputs -> call the outside system -> map results back to app-safe data.
# ============================================
def generate_content(request: ContentIdeaRequest) -> str:
    """Generate a platform-ready post draft without paid APIs."""
    return _trim_for_platform(_build_content_template(request), request.platform)


def suggest_post_time(platform: SocialPlatform, now: datetime) -> tuple[datetime, float]:
    """Public wrapper for choosing a practical post time."""
    return _suggest_next_post_time(platform, now)


def score_post_time(platform: SocialPlatform, scheduled_at: datetime) -> float:
    """Public wrapper for scoring one proposed posting time."""
    return _score_posting_hour(platform, scheduled_at)
