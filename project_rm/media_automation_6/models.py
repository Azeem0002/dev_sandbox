from __future__ import annotations
"""Core models for media_automation_6."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class SocialPlatform(StrEnum):
    """Supported publishing targets for the MVP."""
    X = "x"
    LINKEDIN = "linkedin"
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"


class PostStatus(StrEnum):
    """Lifecycle state for one planned social post."""
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    FAILED = "failed"


class Tone(StrEnum):
    """Content voice options supported by the local AI adapter."""
    PRACTICAL = "practical"
    BOLD = "bold"
    FRIENDLY = "friendly"
    EDUCATIONAL = "educational"


@dataclass(frozen=True)
class ContentIdeaRequest:
    """Clean input for generating one social post draft."""
    topic: str
    platform: SocialPlatform
    tone: Tone
    audience: str
    goal: str


@dataclass(frozen=True)
class ScheduleRequest:
    """Clean input for creating a scheduled social post."""
    topic: str
    platform: SocialPlatform
    tone: Tone
    audience: str
    goal: str
    scheduled_at: datetime | None = None


@dataclass
class SocialPost:
    """One generated or scheduled social post."""
    id: str
    platform: SocialPlatform
    topic: str
    content: str
    scheduled_at: datetime
    status: PostStatus = PostStatus.DRAFT
    audience: str = "solo founders"
    goal: str = "educate"
    score: float | None = None
    published_at: datetime | None = None
    failure_reason: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(frozen=True)
class PublishResult:
    """Result returned by a platform publishing adapter."""
    post_id: str
    platform: SocialPlatform
    published: bool
    external_id: str | None = None
    message: str = ""


@dataclass(frozen=True)
class SchedulerStatus:
    """Small runtime status object for the API boundary."""
    running: bool
    scheduled_jobs: int
