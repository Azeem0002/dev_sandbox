#!/usr/bin/env python3
"""FastAPI boundary for media_automation_6."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

try:
    from .application import generate_post_idea, get_automation_status, list_posts, publish_due_posts, publish_one_post, schedule_post, start_automation, stop_automation
    from .database_adapter import init_db
    from .runtime_support import setup_environment, setup_logger
    from .validation import build_content_idea_request, build_schedule_request
except ImportError:
    from application import generate_post_idea, get_automation_status, list_posts, publish_due_posts, publish_one_post, schedule_post, start_automation, stop_automation
    from database_adapter import init_db
    from runtime_support import setup_environment, setup_logger
    from validation import build_content_idea_request, build_schedule_request


class GeneratePayload(BaseModel):
    """HTTP request body for generating one post draft."""
    topic: str
    platform: str = "linkedin"
    tone: str = "practical"
    audience: str = "solo founders"
    goal: str = "teach one useful lesson"


class SchedulePayload(GeneratePayload):
    """HTTP request body for scheduling one generated post."""
    scheduled_at: str | None = None


class AutomationPayload(BaseModel):
    """HTTP request body for starting background automation."""
    interval_minutes: int = 30
    dry_run: bool = True


app = FastAPI(title="media_automation_6", version="0.1.0")


# ============================================
# API boundary - thin wrapper around orchestration
# ============================================
@app.on_event("startup")
def startup() -> None:
    """Prepare runtime logging and database before serving requests."""
    log_file = setup_environment()
    setup_logger(log_file)
    init_db()


def _post_to_dict(post) -> dict:
    """Convert one post model into API-safe JSON."""
    return {
        "id": post.id,
        "platform": post.platform.value,
        "topic": post.topic,
        "content": post.content,
        "audience": post.audience,
        "goal": post.goal,
        "scheduled_at": post.scheduled_at.isoformat(),
        "status": post.status.value,
        "score": post.score,
        "published_at": post.published_at.isoformat() if post.published_at else None,
        "failure_reason": post.failure_reason,
        "created_at": post.created_at.isoformat(),
    }


@app.get("/health")
def health() -> dict[str, str]:
    """Return a small liveness response."""
    return {"status": "ok"}


@app.post("/generate")
def generate(payload: GeneratePayload) -> dict[str, str]:
    """Generate a social media post draft."""
    try:
        request = build_content_idea_request(topic=payload.topic, platform=payload.platform, tone=payload.tone, audience=payload.audience, goal=payload.goal)
        return {"content": generate_post_idea(request)}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/posts")
def create_post(payload: SchedulePayload) -> dict:
    """Generate and schedule one post."""
    try:
        request = build_schedule_request(topic=payload.topic, platform=payload.platform, tone=payload.tone, audience=payload.audience, goal=payload.goal, scheduled_at=payload.scheduled_at)
        return _post_to_dict(schedule_post(request))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/posts")
def posts(limit: int = 20) -> list[dict]:
    """Return recent saved posts."""
    return [_post_to_dict(post) for post in list_posts(limit)]


@app.post("/posts/{post_id}/publish")
def publish(post_id: str, dry_run: bool = True) -> dict:
    """Publish one post now, using dry-run by default."""
    try:
        return _post_to_dict(publish_one_post(post_id, dry_run=dry_run))
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/publish-due")
def publish_due(dry_run: bool = True) -> list[dict]:
    """Publish all due scheduled posts now."""
    return [_post_to_dict(post) for post in publish_due_posts(dry_run=dry_run)]


@app.post("/automation/start")
def automation_start(payload: AutomationPayload) -> dict:
    """Start recurring background publishing checks."""
    try:
        status = start_automation(interval_minutes=payload.interval_minutes, dry_run=payload.dry_run)
        return {"running": status.running, "scheduled_jobs": status.scheduled_jobs}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/automation/stop")
def automation_stop() -> dict:
    """Stop recurring background publishing checks."""
    status = stop_automation()
    return {"running": status.running, "scheduled_jobs": status.scheduled_jobs}


@app.get("/automation/status")
def automation_status() -> dict:
    """Return background scheduler status."""
    status = get_automation_status()
    return {"running": status.running, "scheduled_jobs": status.scheduled_jobs}
