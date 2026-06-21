#!/usr/bin/env python3
"""Application orchestration for partner_match_8."""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone

try:
    from .ai_adapter import build_group_agent_reply
    from .database_adapter import (
        count_group_members,
        count_followers,
        count_post_comments,
        count_post_likes,
        count_recent_profile_visits,
        delete_group_member,
        delete_follow,
        delete_post_like,
        delete_safety_block,
        fetch_followed_user_ids,
        fetch_group,
        fetch_group_invite_by_token,
        fetch_group_member,
        fetch_group_messages,
        fetch_location,
        fetch_location_candidates,
        fetch_notifications,
        fetch_partner_request,
        fetch_partner_requests_for_user,
        fetch_post_comments,
        fetch_profile,
        fetch_public_post,
        fetch_recent_public_posts,
        fetch_session_by_token_id,
        fetch_user_by_id,
        fetch_user_groups,
        insert_follow,
        insert_group,
        insert_group_invite,
        insert_group_member,
        insert_message,
        insert_notification,
        insert_partner_request,
        insert_post_comment,
        insert_post_like,
        insert_profile_visit,
        insert_public_post,
        insert_report,
        insert_session,
        insert_safety_block,
        is_blocked_between,
        mark_notification_read,
        revoke_group_invite,
        soft_delete_user,
        touch_user_seen,
        update_partner_request_status,
        update_username,
        upsert_location,
        upsert_profile,
        upsert_user_from_google,
    )
    from .google_auth_adapter import verify_google_id_token
    from .location_adapter import distance_km, distance_label
    from .models import (
        AppConfig,
        AuthResult,
        AuthSession,
        AvailabilityStatus,
        BlockUserDTO,
        ChatMessage,
        CommentInputDTO,
        CreateGroupDTO,
        CreateGroupInviteDTO,
        GroupMember,
        GroupInvite,
        GroupRole,
        LocationInputDTO,
        MemberReport,
        MessageInputDTO,
        MessageSenderType,
        NearbyPartner,
        Notification,
        NotificationType,
        PartnerGroup,
        PartnerLocation,
        PartnerProfile,
        PartnerRequest,
        PartnerRequestInputDTO,
        PartnerRequestStatus,
        PresenceStatus,
        ProfileInputDTO,
        PostComment,
        PublicPost,
        PublicPostInputDTO,
        ReportInputDTO,
        SafetyBlock,
        User,
        UserDTO,
        UsernameInputDTO,
        VerificationStatus,
    )
    from .security_adapter import create_access_token, create_token_id, decode_access_token, get_access_token_seconds
except ImportError:
    from ai_adapter import build_group_agent_reply
    from database_adapter import (
        count_group_members,
        count_followers,
        count_post_comments,
        count_post_likes,
        count_recent_profile_visits,
        delete_group_member,
        delete_follow,
        delete_post_like,
        delete_safety_block,
        fetch_followed_user_ids,
        fetch_group,
        fetch_group_invite_by_token,
        fetch_group_member,
        fetch_group_messages,
        fetch_location,
        fetch_location_candidates,
        fetch_notifications,
        fetch_partner_request,
        fetch_partner_requests_for_user,
        fetch_post_comments,
        fetch_profile,
        fetch_public_post,
        fetch_recent_public_posts,
        fetch_session_by_token_id,
        fetch_user_by_id,
        fetch_user_groups,
        insert_follow,
        insert_group,
        insert_group_invite,
        insert_group_member,
        insert_message,
        insert_notification,
        insert_partner_request,
        insert_post_comment,
        insert_post_like,
        insert_profile_visit,
        insert_public_post,
        insert_report,
        insert_session,
        insert_safety_block,
        is_blocked_between,
        mark_notification_read,
        revoke_group_invite,
        soft_delete_user,
        touch_user_seen,
        update_partner_request_status,
        update_username,
        upsert_location,
        upsert_profile,
        upsert_user_from_google,
    )
    from google_auth_adapter import verify_google_id_token
    from location_adapter import distance_km, distance_label
    from models import (
        AppConfig,
        AuthResult,
        AuthSession,
        AvailabilityStatus,
        BlockUserDTO,
        ChatMessage,
        CommentInputDTO,
        CreateGroupDTO,
        CreateGroupInviteDTO,
        GroupMember,
        GroupInvite,
        GroupRole,
        LocationInputDTO,
        MemberReport,
        MessageInputDTO,
        MessageSenderType,
        NearbyPartner,
        Notification,
        NotificationType,
        PartnerGroup,
        PartnerLocation,
        PartnerProfile,
        PartnerRequest,
        PartnerRequestInputDTO,
        PartnerRequestStatus,
        PresenceStatus,
        ProfileInputDTO,
        PostComment,
        PublicPost,
        PublicPostInputDTO,
        ReportInputDTO,
        SafetyBlock,
        User,
        UserDTO,
        UsernameInputDTO,
        VerificationStatus,
    )
    from security_adapter import create_access_token, create_token_id, decode_access_token, get_access_token_seconds


# ============================================
# Application layer - reusable mental map
# ============================================
# Boundary code parses HTTP. This module coordinates use cases and enforces app
# rules. Adapters handle the database, auth verification, tokens, AI, and math.


# ============================================
# Shared private skeleton - start reading here
# ============================================
def _utc_now() -> datetime:
    """Return current UTC time."""
    return datetime.now(timezone.utc)


def _env_int(name: str, default: int) -> int:
    """Read a positive integer from env with a safe fallback."""
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _env_float(name: str, default: float) -> float:
    """Read a positive float from env with a safe fallback."""
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _get_app_config() -> AppConfig:
    """Build runtime limits from env so business rules are not hardcoded."""
    return AppConfig(
        max_group_members=_env_int("PARTNER_MATCH_MAX_GROUP_MEMBERS", 5),
        online_window_seconds=_env_int("PARTNER_MATCH_ONLINE_WINDOW_SECONDS", 300),
        recently_active_window_seconds=_env_int("PARTNER_MATCH_RECENTLY_ACTIVE_WINDOW_SECONDS", 86400),
        default_radius_km=_env_float("PARTNER_MATCH_DEFAULT_RADIUS_KM", 25.0),
    )


def _new_id(prefix: str) -> str:
    """Build a compact public id with a readable prefix."""
    return f"{prefix}_{secrets.token_urlsafe(12)}"


def _presence_for(user: User, now: datetime | None = None) -> PresenceStatus:
    """Derive public active status from last seen time."""
    config = _get_app_config()
    checked_at = now or _utc_now()
    age_seconds = (checked_at - user.last_seen_at).total_seconds()
    if age_seconds <= config.online_window_seconds:
        return PresenceStatus.ONLINE
    if age_seconds <= config.recently_active_window_seconds:
        return PresenceStatus.RECENTLY_ACTIVE
    return PresenceStatus.OFFLINE


def _user_to_dto(user: User) -> UserDTO:
    """Convert an internal user model to API-safe output."""
    verification = VerificationStatus.VERIFIED if user.is_verified else VerificationStatus.UNVERIFIED
    return UserDTO(id=user.id, email=user.email, username=user.username, display_name=user.display_name, avatar_url=user.avatar_url, verification=verification, presence=_presence_for(user))


def _require_current_session(access_token: str) -> tuple[User, AuthSession]:
    """Decode a bearer token, verify its session row, and load the active user."""
    try:
        payload = decode_access_token(access_token)
    except ValueError as error:
        raise ValueError("Please log in again") from error

    token_id = str(payload.get("jti") or "")
    user_id = str(payload.get("sub") or "")
    session = fetch_session_by_token_id(token_id)
    if session is None or session.revoked_at is not None:
        raise ValueError("Please log in again")
    if session.expires_at < _utc_now():
        raise ValueError("Your session expired. Please log in again")
    user = fetch_user_by_id(user_id)
    if user is None:
        raise ValueError("Account is no longer available")
    return user, session


def _require_group(group_id: str) -> PartnerGroup:
    """Load a group or raise a user-friendly error."""
    group = fetch_group(group_id)
    if group is None:
        raise ValueError("Group not found")
    return group


def _require_group_member(group_id: str, user_id: str) -> GroupMember:
    """Require a user to belong to a group."""
    member = fetch_group_member(group_id, user_id)
    if member is None:
        raise ValueError("You are not a member of this group")
    return member


def _require_group_admin(group: PartnerGroup, user_id: str) -> None:
    """Require the current user to be the group admin."""
    if group.admin_user_id != user_id:
        raise ValueError("Only the group admin can do that")


def _profile_or_default(user: User) -> PartnerProfile:
    """Return saved profile or a minimal public profile."""
    return fetch_profile(user.id) or PartnerProfile(
        user_id=user.id,
        display_name=user.display_name,
        bio="",
        mindset_tags=[],
        goal_tags=[],
        sub_goal_tags=[],
        looking_for="",
        availability=AvailabilityStatus.OPEN_TO_PARTNER,
        verification=VerificationStatus.VERIFIED if user.is_verified else VerificationStatus.UNVERIFIED,
        avatar_url=user.avatar_url,
    )


def _build_nearby_partner(user: User, profile: PartnerProfile, location: PartnerLocation, distance: float) -> NearbyPartner:
    """Build public nearby output without exposing exact coordinates."""
    return NearbyPartner(
        user_id=user.id,
        display_name=profile.display_name,
        bio=profile.bio,
        mindset_tags=profile.mindset_tags,
        goal_tags=profile.goal_tags,
        sub_goal_tags=profile.sub_goal_tags,
        looking_for=profile.looking_for,
        availability=profile.availability,
        verification=profile.verification,
        presence=_presence_for(user),
        distance_km=round(distance, 2),
        distance_label=distance_label(distance),
        city=location.city,
        avatar_url=profile.avatar_url,
    )


def _message_to_dict(message: ChatMessage) -> dict:
    """Convert a chat message to API-safe output."""
    return {
        "id": message.id,
        "group_id": message.group_id,
        "sender_id": message.sender_id,
        "sender_type": message.sender_type.value,
        "body": message.body,
        "created_at": message.created_at.isoformat(),
    }


def _notification_to_dict(notification: Notification) -> dict:
    """Convert a notification model to API-safe output."""
    return {
        "id": notification.id,
        "type": notification.notification_type.value,
        "title": notification.title,
        "body": notification.body,
        "related_id": notification.related_id,
        "read_at": notification.read_at.isoformat() if notification.read_at else None,
        "created_at": notification.created_at.isoformat(),
    }


def _partner_request_to_dict(request: PartnerRequest) -> dict:
    """Convert a partner request model to API-safe output."""
    return {
        "id": request.id,
        "requester_user_id": request.requester_user_id,
        "receiver_user_id": request.receiver_user_id,
        "status": request.status.value,
        "message": request.message,
        "created_at": request.created_at.isoformat(),
        "responded_at": request.responded_at.isoformat() if request.responded_at else None,
    }


def _relative_time_label(created_at: datetime) -> str:
    """Turn a timestamp into a short user-facing age label."""
    age_seconds = max(int((_utc_now() - created_at).total_seconds()), 0)
    if age_seconds < 60:
        return "just now"
    age_minutes = age_seconds // 60
    if age_minutes < 60:
        return f"{age_minutes}m ago"
    age_hours = age_minutes // 60
    if age_hours < 24:
        return f"{age_hours}h ago"
    age_days = age_hours // 24
    if age_days < 30:
        return f"{age_days}d ago"
    age_months = age_days // 30
    if age_months < 12:
        return f"{age_months}mo ago"
    return f"{age_months // 12}y ago"


def _post_to_dict(post: PublicPost, *, viewer: User | None = None, score: float | None = None) -> dict:
    """Convert a public post model to API-safe output."""
    author = fetch_user_by_id(post.author_user_id)
    return {
        "id": post.id,
        "author_user_id": post.author_user_id,
        "author_username": author.username if author else None,
        "author_display_name": author.display_name if author else None,
        "post_type": post.post_type.value,
        "body": post.body,
        "media_urls": post.media_urls,
        "tags": post.tags,
        "likes_count": count_post_likes(post.id),
        "comments_count": count_post_comments(post.id),
        "feed_score": round(score, 3) if score is not None else None,
        "created_at": post.created_at.isoformat(),
        "created_ago": _relative_time_label(post.created_at),
    }


def _comment_to_dict(comment: PostComment) -> dict:
    """Convert a post comment model to API-safe output."""
    author = fetch_user_by_id(comment.author_user_id)
    return {
        "id": comment.id,
        "post_id": comment.post_id,
        "author_user_id": comment.author_user_id,
        "author_username": author.username if author else None,
        "body": comment.body,
        "created_at": comment.created_at.isoformat(),
        "created_ago": _relative_time_label(comment.created_at),
    }


def _interest_tags_for(user: User) -> set[str]:
    """Return tags that describe what the user likely wants to see."""
    profile = _profile_or_default(user)
    return set(profile.mindset_tags + profile.goal_tags + profile.sub_goal_tags)


def _score_feed_post(post: PublicPost, user: User, followed_user_ids: set[str], interest_tags: set[str]) -> float:
    """Score feed relevance using follows, shared tags, engagement, post lane, and recency."""
    score = 0.0
    if post.author_user_id in followed_user_ids:
        score += 5.0
    score += len(set(post.tags) & interest_tags) * 2.0
    score += min(count_post_likes(post.id), 20) * 0.15
    score += min(count_post_comments(post.id), 20) * 0.25
    if post.post_type.value == "building":
        score += 0.75
    age_hours = max((_utc_now() - post.created_at).total_seconds() / 3600, 0)
    score += max(0.0, 4.0 - (age_hours / 12))
    return score


def _group_to_dict(group: PartnerGroup) -> dict:
    """Convert a group model to API-safe output."""
    return {
        "id": group.id,
        "name": group.name,
        "purpose": group.purpose,
        "admin_user_id": group.admin_user_id,
        "member_count": count_group_members(group.id),
        "roles": [role.value for role in GroupRole],
        "created_at": group.created_at.isoformat(),
    }


def _invite_to_dict(invite: GroupInvite) -> dict:
    """Convert an invite model to API-safe output."""
    return {
        "id": invite.id,
        "group_id": invite.group_id,
        "token": invite.token,
        "join_path": f"/groups/invites/{invite.token}/join",
        "expires_at": invite.expires_at.isoformat() if invite.expires_at else None,
        "revoked_at": invite.revoked_at.isoformat() if invite.revoked_at else None,
        "created_at": invite.created_at.isoformat(),
    }


# ============================================
# Public application API - use-case orchestration
# ============================================
def login_with_google(id_token: str) -> AuthResult:
    """Log in or create a user from a Google ID token."""
    now = _utc_now()
    identity = verify_google_id_token(id_token)
    user = upsert_user_from_google(identity, now)
    expires_in_seconds = get_access_token_seconds()
    token_id = create_token_id()
    session = AuthSession(
        id=_new_id("session"),
        user_id=user.id,
        token_id=token_id,
        expires_at=now + timedelta(seconds=expires_in_seconds),
    )
    insert_session(session)
    access_token = create_access_token(user_id=user.id, token_id=token_id, expires_in_seconds=expires_in_seconds)
    return AuthResult(user=user, session=session, access_token=access_token, expires_in_seconds=expires_in_seconds)


def get_current_user(access_token: str) -> User:
    """Return the active user for a bearer token."""
    user, _session = _require_current_session(access_token)
    return user


def get_current_user_dto(access_token: str) -> UserDTO:
    """Return API-safe current-user output."""
    return _user_to_dto(get_current_user(access_token))


def mark_user_active(user: User) -> UserDTO:
    """Update active status heartbeat."""
    updated = touch_user_seen(user.id, _utc_now())
    if updated is None:
        raise ValueError("Account is no longer available")
    return _user_to_dto(updated)


def update_my_username(user: User, payload: UsernameInputDTO) -> UserDTO:
    """Update the current user's unique public username."""
    return _user_to_dto(update_username(user.id, payload.username))


def update_my_profile(user: User, payload: ProfileInputDTO) -> PartnerProfile:
    """Save the current user's public partner profile."""
    profile = PartnerProfile(
        user_id=user.id,
        display_name=payload.display_name,
        bio=payload.bio,
        mindset_tags=payload.mindset_tags,
        goal_tags=payload.goal_tags,
        sub_goal_tags=payload.sub_goal_tags,
        looking_for=payload.looking_for,
        availability=payload.availability,
        verification=VerificationStatus.VERIFIED if user.is_verified else VerificationStatus.UNVERIFIED,
        avatar_url=user.avatar_url,
    )
    return upsert_profile(profile)


def get_my_profile(user: User) -> PartnerProfile:
    """Return the current user's public partner profile."""
    return _profile_or_default(user)


def view_profile(viewer: User, profile_user_id: str) -> dict:
    """Return a public profile and record a visit when viewing another user."""
    target = fetch_user_by_id(profile_user_id)
    if target is None:
        raise ValueError("Profile not found")
    if is_blocked_between(viewer.id, target.id):
        raise ValueError("Profile is not available")
    if viewer.id != target.id:
        insert_profile_visit(viewer.id, target.id, _utc_now())
    profile = _profile_or_default(target)
    data = _profile_to_public_dict(profile, target)
    data["followers_count"] = count_followers(target.id)
    data["recent_visits_count"] = count_recent_profile_visits(target.id, _utc_now() - timedelta(days=7))
    return data


def _profile_to_public_dict(profile: PartnerProfile, user: User) -> dict:
    """Convert profile plus account into public profile output."""
    return {
        "user_id": profile.user_id,
        "username": user.username,
        "display_name": profile.display_name,
        "bio": profile.bio,
        "mindset_tags": profile.mindset_tags,
        "goal_tags": profile.goal_tags,
        "sub_goal_tags": profile.sub_goal_tags,
        "looking_for": profile.looking_for,
        "availability": profile.availability.value,
        "verification": profile.verification.value,
        "avatar_url": profile.avatar_url,
    }


def update_my_location(user: User, payload: LocationInputDTO) -> PartnerLocation:
    """Save opt-in location for nearby matching."""
    location = PartnerLocation(
        user_id=user.id,
        latitude=payload.latitude,
        longitude=payload.longitude,
        city=payload.city,
        is_enabled=payload.is_enabled,
        updated_at=_utc_now(),
    )
    return upsert_location(location)


def find_nearby_partners(user: User, radius_km: float | None = None) -> list[NearbyPartner]:
    """Find nearby opt-in partners without leaking exact coordinates."""
    config = _get_app_config()
    search_radius = radius_km if radius_km is not None else config.default_radius_km
    if search_radius <= 0 or search_radius > 500:
        raise ValueError("radius_km must be between 1 and 500")

    my_location = fetch_location(user.id)
    if my_location is None or not my_location.is_enabled:
        raise ValueError("Turn on location before searching for nearby partners")

    nearby: list[NearbyPartner] = []
    for candidate_user, candidate_profile, candidate_location in fetch_location_candidates(user.id):
        if is_blocked_between(user.id, candidate_user.id):
            continue
        distance = distance_km(my_location.latitude, my_location.longitude, candidate_location.latitude, candidate_location.longitude)
        if distance <= search_radius:
            profile = candidate_profile or _profile_or_default(candidate_user)
            if profile.availability != AvailabilityStatus.OPEN_TO_PARTNER:
                continue
            nearby.append(_build_nearby_partner(candidate_user, profile, candidate_location, distance))
    return sorted(nearby, key=lambda item: item.distance_km)


def create_group_for_user(user: User, payload: CreateGroupDTO) -> dict:
    """Create a teammate group with the current user as admin."""
    now = _utc_now()
    group = PartnerGroup(id=_new_id("group"), name=payload.name, purpose=payload.purpose, admin_user_id=user.id, created_at=now)
    admin_member = GroupMember(group_id=group.id, user_id=user.id, role=GroupRole.ADMIN, joined_at=now)
    return _group_to_dict(insert_group(group, admin_member))


def create_public_post(user: User, payload: PublicPostInputDTO) -> dict:
    """Create a public shoutout/building feed post."""
    post = PublicPost(
        id=_new_id("post"),
        author_user_id=user.id,
        post_type=payload.post_type,
        body=payload.body,
        media_urls=payload.media_urls,
        tags=payload.tags,
        created_at=_utc_now(),
    )
    saved = insert_public_post(post)
    return _post_to_dict(saved, viewer=user)


def get_feed(user: User, limit: int = 50) -> list[dict]:
    """Return a ranked feed based on follows, tags, engagement, and recency."""
    bounded_limit = min(max(limit, 1), 100)
    followed_user_ids = fetch_followed_user_ids(user.id)
    interest_tags = _interest_tags_for(user)
    scored: list[tuple[float, PublicPost]] = []
    for post in fetch_recent_public_posts(limit=200):
        if post.author_user_id != user.id and is_blocked_between(user.id, post.author_user_id):
            continue
        score = _score_feed_post(post, user, followed_user_ids, interest_tags)
        scored.append((score, post))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [_post_to_dict(post, viewer=user, score=score) for score, post in scored[:bounded_limit]]


def like_post(user: User, post_id: str) -> dict[str, int | bool]:
    """Like a public post."""
    post = fetch_public_post(post_id)
    if post is None:
        raise ValueError("Post not found")
    if is_blocked_between(user.id, post.author_user_id):
        raise ValueError("Post is not available")
    created = insert_post_like(post_id, user.id, _utc_now())
    if created and post.author_user_id != user.id:
        insert_notification(Notification(id=_new_id("notif"), user_id=post.author_user_id, notification_type=NotificationType.GENERAL, title="New like", body=f"{user.display_name} liked your post", related_id=post_id, read_at=None, created_at=_utc_now()))
    return {"liked": True, "likes_count": count_post_likes(post_id)}


def unlike_post(user: User, post_id: str) -> dict[str, int | bool]:
    """Remove a public post like."""
    delete_post_like(post_id, user.id)
    return {"liked": False, "likes_count": count_post_likes(post_id)}


def comment_on_post(user: User, post_id: str, payload: CommentInputDTO) -> dict:
    """Comment on a public post."""
    post = fetch_public_post(post_id)
    if post is None:
        raise ValueError("Post not found")
    if is_blocked_between(user.id, post.author_user_id):
        raise ValueError("Post is not available")
    comment = PostComment(id=_new_id("comment"), post_id=post_id, author_user_id=user.id, body=payload.body, created_at=_utc_now())
    saved = insert_post_comment(comment)
    if post.author_user_id != user.id:
        insert_notification(Notification(id=_new_id("notif"), user_id=post.author_user_id, notification_type=NotificationType.GENERAL, title="New comment", body=f"{user.display_name} commented on your post", related_id=post_id, read_at=None, created_at=_utc_now()))
    return _comment_to_dict(saved)


def list_post_comments(user: User, post_id: str, limit: int = 50) -> list[dict]:
    """List comments on a public post."""
    post = fetch_public_post(post_id)
    if post is None:
        raise ValueError("Post not found")
    if is_blocked_between(user.id, post.author_user_id):
        raise ValueError("Post is not available")
    return [_comment_to_dict(comment) for comment in fetch_post_comments(post_id, min(max(limit, 1), 100))]


def follow_user(user: User, followed_user_id: str) -> dict[str, int | bool]:
    """Follow a user for updates."""
    if followed_user_id == user.id:
        raise ValueError("You cannot follow yourself")
    target = fetch_user_by_id(followed_user_id)
    if target is None:
        raise ValueError("User not found")
    if is_blocked_between(user.id, followed_user_id):
        raise ValueError("User is not available")
    created = insert_follow(user.id, followed_user_id, _utc_now())
    if created:
        insert_notification(Notification(id=_new_id("notif"), user_id=followed_user_id, notification_type=NotificationType.GENERAL, title="New follower", body=f"{user.display_name} followed you", related_id=user.id, read_at=None, created_at=_utc_now()))
    return {"following": True, "followers_count": count_followers(followed_user_id)}


def unfollow_user(user: User, followed_user_id: str) -> dict[str, int | bool]:
    """Unfollow a user."""
    delete_follow(user.id, followed_user_id)
    return {"following": False, "followers_count": count_followers(followed_user_id)}


def request_partner(user: User, payload: PartnerRequestInputDTO) -> dict:
    """Send a one-to-one partner request."""
    if payload.receiver_user_id == user.id:
        raise ValueError("You cannot request yourself")
    receiver = fetch_user_by_id(payload.receiver_user_id)
    if receiver is None:
        raise ValueError("User not found")
    if is_blocked_between(user.id, receiver.id):
        raise ValueError("User is not available")
    request = PartnerRequest(id=_new_id("preq"), requester_user_id=user.id, receiver_user_id=receiver.id, status=PartnerRequestStatus.PENDING, message=payload.message, created_at=_utc_now())
    saved = insert_partner_request(request)
    insert_notification(Notification(id=_new_id("notif"), user_id=receiver.id, notification_type=NotificationType.PARTNER_REQUEST, title="New partner request", body=f"{user.display_name} wants to connect as a partner", related_id=saved.id, read_at=None, created_at=_utc_now()))
    return _partner_request_to_dict(saved)


def respond_to_partner_request(user: User, request_id: str, status: PartnerRequestStatus) -> dict:
    """Accept or decline a partner request."""
    if status == PartnerRequestStatus.PENDING:
        raise ValueError("Response must be accepted or declined")
    existing = fetch_partner_request(request_id)
    if existing is None or existing.receiver_user_id != user.id:
        raise ValueError("Partner request not found")
    updated = update_partner_request_status(request_id, user.id, status, _utc_now())
    if updated is None:
        raise ValueError("Partner request is no longer pending")
    insert_notification(Notification(id=_new_id("notif"), user_id=updated.requester_user_id, notification_type=NotificationType.PARTNER_REQUEST, title="Partner request update", body=f"{user.display_name} {status.value} your partner request", related_id=updated.id, read_at=None, created_at=_utc_now()))
    return _partner_request_to_dict(updated)


def list_partner_requests(user: User, limit: int = 50) -> list[dict]:
    """List partner requests received by the current user."""
    return [_partner_request_to_dict(request) for request in fetch_partner_requests_for_user(user.id, min(max(limit, 1), 100))]


def list_notifications(user: User, limit: int = 50) -> list[dict]:
    """List notifications for the current user."""
    return [_notification_to_dict(notification) for notification in fetch_notifications(user.id, min(max(limit, 1), 100))]


def read_notification(user: User, notification_id: str) -> dict[str, bool]:
    """Mark a notification as read."""
    return {"read": mark_notification_read(notification_id, user.id, _utc_now())}


def get_profile_visit_stats(user: User) -> dict[str, int]:
    """Return recent profile visit counts for the current user."""
    now = _utc_now()
    return {
        "recent_count": count_recent_profile_visits(user.id, now - timedelta(days=1)),
        "weekly_count": count_recent_profile_visits(user.id, now - timedelta(days=7)),
    }


def list_my_groups(user: User) -> list[dict]:
    """List groups where the current user is a member."""
    return [_group_to_dict(group) for group in fetch_user_groups(user.id)]


def add_group_partner(admin: User, group_id: str, partner_user_id: str) -> dict:
    """Add one partner to a group, subject to admin rights and group limit."""
    config = _get_app_config()
    group = _require_group(group_id)
    _require_group_admin(group, admin.id)
    partner = fetch_user_by_id(partner_user_id)
    if partner is None:
        raise ValueError("Partner account not found")
    if is_blocked_between(admin.id, partner_user_id):
        raise ValueError("You cannot add a blocked partner")
    if fetch_group_member(group_id, partner_user_id) is not None:
        raise ValueError("Partner is already in this group")
    if count_group_members(group_id) >= config.max_group_members:
        raise ValueError(f"Groups can have at most {config.max_group_members} members")
    member = GroupMember(group_id=group_id, user_id=partner_user_id, role=GroupRole.PARTNER, joined_at=_utc_now())
    insert_group_member(member)
    return _group_to_dict(group)


def create_group_invite(admin: User, group_id: str, payload: CreateGroupInviteDTO) -> dict:
    """Create an invite link for a group."""
    group = _require_group(group_id)
    _require_group_admin(group, admin.id)
    now = _utc_now()
    expires_at = now + timedelta(hours=payload.expires_in_hours) if payload.expires_in_hours is not None else None
    invite = GroupInvite(
        id=_new_id("invite"),
        group_id=group_id,
        token=secrets.token_urlsafe(18),
        created_by_user_id=admin.id,
        expires_at=expires_at,
        revoked_at=None,
        created_at=now,
    )
    return _invite_to_dict(insert_group_invite(invite))


def join_group_by_invite(user: User, token: str) -> dict:
    """Join a group using a live invite token."""
    config = _get_app_config()
    invite = fetch_group_invite_by_token(token)
    if invite is None or invite.revoked_at is not None:
        raise ValueError("Invite link is invalid")
    if invite.expires_at is not None and invite.expires_at < _utc_now():
        raise ValueError("Invite link has expired")
    group = _require_group(invite.group_id)
    if is_blocked_between(user.id, group.admin_user_id):
        raise ValueError("You cannot join this group")
    if fetch_group_member(group.id, user.id) is not None:
        return _group_to_dict(group)
    if count_group_members(group.id) >= config.max_group_members:
        raise ValueError(f"Groups can have at most {config.max_group_members} members")
    insert_group_member(GroupMember(group_id=group.id, user_id=user.id, role=GroupRole.PARTNER, joined_at=_utc_now()))
    return _group_to_dict(group)


def revoke_invite(admin: User, token: str) -> dict[str, str]:
    """Revoke a group invite link."""
    invite = fetch_group_invite_by_token(token)
    if invite is None:
        raise ValueError("Invite link not found")
    group = _require_group(invite.group_id)
    _require_group_admin(group, admin.id)
    if not revoke_group_invite(token, _utc_now()):
        raise ValueError("Invite link is already revoked")
    return {"status": "revoked"}


def remove_group_partner(admin: User, group_id: str, partner_user_id: str) -> dict:
    """Remove one partner from a group."""
    group = _require_group(group_id)
    _require_group_admin(group, admin.id)
    if partner_user_id == group.admin_user_id:
        raise ValueError("Transfer admin before removing the group admin")
    if not delete_group_member(group_id, partner_user_id):
        raise ValueError("Partner is not in this group")
    return _group_to_dict(group)


def send_group_message(user: User, group_id: str, payload: MessageInputDTO) -> list[dict]:
    """Store a group message and optionally let the AI teammate answer."""
    group = _require_group(group_id)
    _require_group_member(group_id, user.id)
    now = _utc_now()
    user_message = ChatMessage(
        id=_new_id("msg"),
        group_id=group_id,
        sender_id=user.id,
        sender_type=MessageSenderType.USER,
        body=payload.body,
        created_at=now,
    )
    insert_message(user_message)
    messages = fetch_group_messages(group_id)
    created = [user_message]

    if payload.body.casefold().startswith("@agent"):
        agent_message = ChatMessage(
            id=_new_id("msg"),
            group_id=group_id,
            sender_id=None,
            sender_type=MessageSenderType.AI_AGENT,
            body=build_group_agent_reply(group, messages),
            created_at=_utc_now(),
        )
        insert_message(agent_message)
        created.append(agent_message)
    return [_message_to_dict(message) for message in created]


def get_group_messages(user: User, group_id: str, limit: int = 50) -> list[dict]:
    """Return group messages if the current user belongs to the group."""
    _require_group(group_id)
    _require_group_member(group_id, user.id)
    bounded_limit = min(max(limit, 1), 100)
    return [_message_to_dict(message) for message in fetch_group_messages(group_id, bounded_limit)]


def report_target(user: User, payload: ReportInputDTO) -> dict:
    """Store a user or group report for review."""
    if payload.target_type.value == "user" and fetch_user_by_id(payload.target_id) is None:
        raise ValueError("Reported user not found")
    if payload.target_type.value == "group" and fetch_group(payload.target_id) is None:
        raise ValueError("Reported group not found")
    report = MemberReport(
        id=_new_id("report"),
        reporter_user_id=user.id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        reason=payload.reason,
        details=payload.details,
        created_at=_utc_now(),
    )
    saved = insert_report(report)
    return {"id": saved.id, "status": "received"}


def block_user(user: User, payload: BlockUserDTO) -> dict[str, str]:
    """Block another user from matching and invite flows."""
    if payload.blocked_user_id == user.id:
        raise ValueError("You cannot block yourself")
    if fetch_user_by_id(payload.blocked_user_id) is None:
        raise ValueError("User not found")
    insert_safety_block(SafetyBlock(blocker_user_id=user.id, blocked_user_id=payload.blocked_user_id, created_at=_utc_now()))
    return {"status": "blocked"}


def unblock_user(user: User, blocked_user_id: str) -> dict[str, str]:
    """Remove a safety block."""
    if not delete_safety_block(user.id, blocked_user_id):
        raise ValueError("Block not found")
    return {"status": "unblocked"}


def delete_my_account(user: User) -> dict[str, str]:
    """Soft-delete the current user account and revoke active sessions."""
    if not soft_delete_user(user.id, _utc_now()):
        raise ValueError("Account is already deleted")
    return {"status": "deleted"}
