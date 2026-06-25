#!/usr/bin/env python3
"""SQLite database adapter for media_automation_6."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

try:
    from .models import PostStatus, SocialPlatform, SocialPost
    from .runtime_adapter import get_platform_dirs
except ImportError:
    from models import PostStatus, SocialPlatform, SocialPost
    from runtime_adapter import get_platform_dirs


# ============================================
# Database adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================
dirs = get_platform_dirs()


def _get_db_path() -> Path:
    """Return the database file path."""
    # Keep path getters pure: return the path only.
    return Path(dirs.user_data_dir) / "media_automation.db"


DB_PATH = _get_db_path()


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse stored ISO datetime text into datetime."""
    return datetime.fromisoformat(value) if value else None


def _init_db() -> None:
    """Initialize database schema and indexes."""
    # Init is the explicit setup step, so parent-dir creation belongs here.
    DB_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id TEXT PRIMARY KEY,
            platform TEXT NOT NULL,
            topic TEXT NOT NULL,
            content TEXT NOT NULL,
            audience TEXT NOT NULL,
            goal TEXT NOT NULL,
            scheduled_at TEXT NOT NULL,
            status TEXT NOT NULL,
            score REAL,
            published_at TEXT,
            failure_reason TEXT,
            created_at TEXT NOT NULL
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_status_scheduled_at ON posts(status, scheduled_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_platform_status ON posts(platform, status)")
        logger.debug("Media automation database initialized")


def _row_to_post(row: sqlite3.Row) -> SocialPost:
    """Map one SQLite row into an internal post model."""
    return SocialPost(
        id=row["id"],
        platform=SocialPlatform(row["platform"]),
        topic=row["topic"],
        content=row["content"],
        audience=row["audience"],
        goal=row["goal"],
        scheduled_at=datetime.fromisoformat(row["scheduled_at"]),
        status=PostStatus(row["status"]),
        score=row["score"],
        published_at=_parse_datetime(row["published_at"]),
        failure_reason=row["failure_reason"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


@retry(
    retry=retry_if_exception_type(sqlite3.OperationalError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    reraise=True,
)
def _insert_post(post: SocialPost) -> SocialPost:
    """Save one generated or scheduled post to SQLite."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO posts (
                id, platform, topic, content, audience, goal, scheduled_at,
                status, score, published_at, failure_reason, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                post.id,
                post.platform.value,
                post.topic,
                post.content,
                post.audience,
                post.goal,
                post.scheduled_at.isoformat(),
                post.status.value,
                post.score,
                post.published_at.isoformat() if post.published_at else None,
                post.failure_reason,
                post.created_at.isoformat(),
            ),
        )
    return post


def _fetch_post_by_id(post_id: str) -> SocialPost | None:
    """Fetch one post by id."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    return _row_to_post(row) if row else None


def _fetch_due_posts(now: datetime, limit: int = 25) -> list[SocialPost]:
    """Fetch scheduled posts due for publishing."""
    # Query by status + scheduled_at so the background checker can stay simple.
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM posts
            WHERE status = ? AND scheduled_at <= ?
            ORDER BY scheduled_at ASC
            LIMIT ?
            """,
            (PostStatus.SCHEDULED.value, now.isoformat(), limit),
        ).fetchall()
    return [_row_to_post(row) for row in rows]


def _fetch_recent_posts(limit: int = 20) -> list[SocialPost]:
    """Load recent posts from SQLite."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM posts ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [_row_to_post(row) for row in rows]


def _update_post_status(
    post_id: str,
    status: PostStatus,
    *,
    published_at: datetime | None = None,
    failure_reason: str | None = None,
) -> bool:
    """Update one post lifecycle status."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "UPDATE posts SET status = ?, published_at = ?, failure_reason = ? WHERE id = ?",
            (status.value, published_at.isoformat() if published_at else None, failure_reason, post_id),
        )
    return cursor.rowcount > 0


# ============================================
# Public adapter API - stable reusable surface
# Responsibility-order adapters are grouped by the job they do, not by install/start/stop lifecycle.
# Read them as: prepare inputs -> call the outside system -> map results back to app-safe data.
# ============================================
def get_db_path() -> Path:
    """Return the database file path."""
    return DB_PATH


def init_db() -> None:
    """Public wrapper for initializing media automation persistence."""
    _init_db()


def insert_post(post: SocialPost) -> SocialPost:
    """Public wrapper for saving one post."""
    return _insert_post(post)


def fetch_post_by_id(post_id: str) -> SocialPost | None:
    """Public wrapper for fetching a post by id."""
    return _fetch_post_by_id(post_id)


def fetch_due_posts(now: datetime, limit: int = 25) -> list[SocialPost]:
    """Public wrapper for loading due scheduled posts."""
    return _fetch_due_posts(now, limit)


def fetch_recent_posts(limit: int = 20) -> list[SocialPost]:
    """Public wrapper for loading recent posts."""
    return _fetch_recent_posts(limit)


def update_post_status(post_id: str, status: PostStatus, *, published_at: datetime | None = None, failure_reason: str | None = None) -> bool:
    """Public wrapper for updating one post lifecycle status."""
    return _update_post_status(post_id, status, published_at=published_at, failure_reason=failure_reason)
