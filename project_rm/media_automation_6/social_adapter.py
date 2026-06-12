"""Social platform publishing adapter."""

import os
from datetime import datetime, timezone

from loguru import logger

try:
    from .models import PublishResult, SocialPlatform, SocialPost
except ImportError:
    from models import PublishResult, SocialPlatform, SocialPost


# ============================================
# Social adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================
def _get_platform_token(platform: SocialPlatform) -> str | None:
    """Resolve the environment variable token for one platform."""
    # Keep credentials at the boundary. Application/core code should never know env-var names.
    return os.getenv(f"MEDIA_AUTOMATION_{platform.value.upper()}_TOKEN")


def _publish_dry_run(post: SocialPost) -> PublishResult:
    """Pretend to publish without touching external APIs."""
    # Dry-run is the safe default while platform API credentials/app approval are not configured.
    logger.info(f"DRY RUN publish to {post.platform.value}: {post.content[:80]}")
    return PublishResult(post_id=post.id, platform=post.platform, published=True, external_id=f"dry-run-{post.id}", message="Dry-run publish completed")


def _publish_with_token(post: SocialPost, token: str) -> PublishResult:
    """Placeholder for real platform API calls."""
    # Real X/LinkedIn/Facebook/Instagram clients should be implemented here, not in application.py.
    del token
    return PublishResult(post_id=post.id, platform=post.platform, published=False, message="Real platform publishing is not implemented yet")


# ============================================
# Public adapter API - stable reusable surface
# ============================================
def publish_post(post: SocialPost, *, dry_run: bool = True) -> PublishResult:
    """Publish one post or simulate publishing when dry_run is enabled."""
    if dry_run:
        return _publish_dry_run(post)
    token = _get_platform_token(post.platform)
    if not token:
        return PublishResult(post_id=post.id, platform=post.platform, published=False, message=f"Missing token for {post.platform.value}")
    return _publish_with_token(post, token)


def utc_now() -> datetime:
    """Return timezone-aware UTC now for publish decisions."""
    return datetime.now(timezone.utc)
