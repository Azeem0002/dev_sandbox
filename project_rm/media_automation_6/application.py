"""Application/orchestration layer for media_automation_6."""

from datetime import datetime, timezone
import uuid

try:
    from .ai_adapter import generate_content, score_post_time, suggest_post_time
    from .database_adapter import fetch_due_posts, fetch_post_by_id, fetch_recent_posts, insert_post, update_post_status
    from .models import ContentIdeaRequest, PostStatus, ScheduleRequest, SchedulerStatus, SocialPost
    from .scheduler_adapter import get_scheduler_status, start_scheduler, stop_scheduler
    from .social_adapter import publish_post, utc_now
except ImportError:
    from ai_adapter import generate_content, score_post_time, suggest_post_time
    from database_adapter import fetch_due_posts, fetch_post_by_id, fetch_recent_posts, insert_post, update_post_status
    from models import ContentIdeaRequest, PostStatus, ScheduleRequest, SchedulerStatus, SocialPost
    from scheduler_adapter import get_scheduler_status, start_scheduler, stop_scheduler
    from social_adapter import publish_post, utc_now


def _build_post(data: ScheduleRequest) -> SocialPost:
    """Build one scheduled post from validated scheduling input."""
    idea_request = ContentIdeaRequest(data.topic, data.platform, data.tone, data.audience, data.goal)
    suggested_at, suggested_score = suggest_post_time(data.platform, utc_now())
    scheduled_at = data.scheduled_at or suggested_at
    score = score_post_time(data.platform, scheduled_at) if data.scheduled_at else suggested_score
    return SocialPost(
        id=str(uuid.uuid4()),
        platform=data.platform,
        topic=data.topic,
        content=generate_content(idea_request),
        scheduled_at=scheduled_at,
        status=PostStatus.SCHEDULED,
        audience=data.audience,
        goal=data.goal,
        score=score,
    )


def _mark_published(post: SocialPost) -> SocialPost:
    """Move a post model into published state after adapter success."""
    post.status = PostStatus.PUBLISHED
    post.published_at = datetime.now(timezone.utc)
    return post


def _mark_failed(post: SocialPost, reason: str) -> SocialPost:
    """Move a post model into failed state after adapter failure."""
    post.status = PostStatus.FAILED
    post.failure_reason = reason
    return post


# ============================================
# Application / Orchestration - Public use cases
# Start reading internals from here.
# ============================================
def generate_post_idea(data: ContentIdeaRequest) -> str:
    """Generate one social media post draft."""
    return generate_content(data)


def schedule_post(data: ScheduleRequest) -> SocialPost:
    """Generate and save one scheduled social media post."""
    return insert_post(_build_post(data))


def publish_one_post(post_id: str, *, dry_run: bool = True) -> SocialPost:
    """Publish one saved post immediately."""
    post = fetch_post_by_id(post_id)
    if post is None:
        raise ValueError(f"Post '{post_id}' not found")
    result = publish_post(post, dry_run=dry_run)
    if result.published:
        updated = _mark_published(post)
        update_post_status(post.id, updated.status, published_at=updated.published_at)
        return updated
    updated = _mark_failed(post, result.message)
    update_post_status(post.id, updated.status, failure_reason=updated.failure_reason)
    return updated


def publish_due_posts(*, dry_run: bool = True) -> list[SocialPost]:
    """Publish scheduled posts whose time has arrived."""
    return [publish_one_post(post.id, dry_run=dry_run) for post in fetch_due_posts(utc_now())]


def list_posts(limit: int = 20) -> list[SocialPost]:
    """Return recent saved posts."""
    return fetch_recent_posts(limit)


def start_automation(*, interval_minutes: int = 30, dry_run: bool = True) -> SchedulerStatus:
    """Start recurring background publishing checks."""
    if interval_minutes < 1:
        raise ValueError("interval_minutes must be at least 1")

    def job() -> None:
        publish_due_posts(dry_run=dry_run)

    return start_scheduler(job, interval_minutes=interval_minutes)


def stop_automation() -> SchedulerStatus:
    """Stop recurring background publishing checks."""
    return stop_scheduler()


def get_automation_status() -> SchedulerStatus:
    """Return recurring scheduler status."""
    return get_scheduler_status()
