"""Validation/parsing helpers for media_automation_6."""

from datetime import datetime, timezone
from math import ceil

import pytimeparse

try:
    from .models import ContentIdeaRequest, ScheduleRequest, SocialPlatform, Tone
except ImportError:
    from models import ContentIdeaRequest, ScheduleRequest, SocialPlatform, Tone


MIN_DURATION_SECONDS = 60


def _normalize_required_text(value: str, field_name: str, *, max_length: int = 280) -> str:
    """Normalize required human text and reject empty/huge values early."""
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned:
        raise ValueError(f"{field_name} cannot be empty")
    if len(cleaned) > max_length:
        raise ValueError(f"{field_name} must be {max_length} characters or less")
    return cleaned


def parse_social_platform(value: str) -> SocialPlatform:
    """Parse user/API text into a supported social platform."""
    return SocialPlatform(value.strip().lower())


def parse_tone(value: str) -> Tone:
    """Parse user/API text into a supported AI writing tone."""
    return Tone(value.strip().lower())


def parse_duration_seconds(value: int | str, *, field_name: str = "duration") -> int:
    """Parse flexible time input like `3d`, `1m`, `1h 30m`, or plain seconds."""
    if isinstance(value, int):
        seconds = value
    elif isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"{field_name} cannot be empty")
        if cleaned.isdigit():
            seconds = int(cleaned)
        else:
            parsed = pytimeparse.parse(cleaned)
            if parsed is None:
                raise ValueError(f"Invalid {field_name}: {value}")
            seconds = int(parsed)
    else:
        raise ValueError(f"{field_name} must be a number or time expression")

    if seconds < MIN_DURATION_SECONDS:
        raise ValueError(f"{field_name} must be at least 1 minute")
    return seconds


def parse_duration_minutes(value: int | str, *, field_name: str = "duration") -> int:
    """Parse human time input and return whole minutes, rounding up partial minutes."""
    if isinstance(value, int):
        minutes = value
    elif isinstance(value, str):
        cleaned = value.strip()
        if cleaned.isdigit():
            minutes = int(cleaned)
        else:
            minutes = ceil(parse_duration_seconds(cleaned, field_name=field_name) / 60)
    else:
        raise ValueError(f"{field_name} must be a number or time expression")
    return minutes


def normalize_interval_minutes(value: int | str) -> int:
    """Clamp automation polling interval to a practical scheduler range."""
    minutes = parse_duration_minutes(value, field_name="interval_minutes")
    if minutes < 1:
        raise ValueError("interval_minutes must be at least 1")
    if minutes > 1440:
        raise ValueError("interval_minutes must be 1440 or less")
    return minutes


def parse_optional_datetime(value: str | None) -> datetime | None:
    """Parse optional ISO datetime and normalize it to timezone-aware UTC."""
    if value is None or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError as error:
        raise ValueError("scheduled_at must be ISO datetime, e.g. 2026-06-12T09:00:00+01:00") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def build_content_idea_request(*, topic: str, platform: str, tone: str, audience: str, goal: str) -> ContentIdeaRequest:
    """Build clean content-generation input from raw boundary values."""
    return ContentIdeaRequest(
        topic=_normalize_required_text(topic, "Topic"),
        platform=parse_social_platform(platform),
        tone=parse_tone(tone),
        audience=_normalize_required_text(audience, "Audience"),
        goal=_normalize_required_text(goal, "Goal"),
    )


def build_schedule_request(
    *,
    topic: str,
    platform: str,
    tone: str,
    audience: str,
    goal: str,
    scheduled_at: str | None,
) -> ScheduleRequest:
    """Build clean scheduled-post input from raw boundary values."""
    return ScheduleRequest(
        topic=_normalize_required_text(topic, "Topic"),
        platform=parse_social_platform(platform),
        tone=parse_tone(tone),
        audience=_normalize_required_text(audience, "Audience"),
        goal=_normalize_required_text(goal, "Goal"),
        scheduled_at=parse_optional_datetime(scheduled_at),
    )
