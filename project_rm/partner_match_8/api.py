#!/usr/bin/env python3
"""FastAPI boundary for partner_match_8."""

from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException

try:
    from .application import (
        add_group_partner,
        block_user,
        comment_on_post,
        create_group_for_user,
        create_group_invite,
        create_public_post,
        delete_my_account,
        find_nearby_partners,
        follow_user,
        get_feed,
        get_current_user,
        get_current_user_dto,
        get_group_messages,
        get_my_profile,
        get_profile_visit_stats,
        join_group_by_invite,
        like_post,
        list_notifications,
        list_partner_requests,
        list_post_comments,
        list_my_groups,
        login_with_google,
        mark_user_active,
        read_notification,
        remove_group_partner,
        request_partner,
        respond_to_partner_request,
        revoke_invite,
        report_target,
        send_group_message,
        unblock_user,
        unfollow_user,
        unlike_post,
        update_my_location,
        update_my_profile,
        update_my_username,
        view_profile,
    )
    from .database_adapter import init_db
    from .models import AddGroupMemberDTO, BlockUserDTO, CommentInputDTO, CreateGroupDTO, CreateGroupInviteDTO, GoogleLoginDTO, LocationInputDTO, MessageInputDTO, PartnerRequestInputDTO, PartnerRequestStatus, ProfileInputDTO, PublicPostInputDTO, ReportInputDTO, TokenDTO, User, UsernameInputDTO
    from .runtime_adapter import setup_environment, setup_logger
    from .validation import build_block_input, build_comment_input, build_group_input, build_invite_input, build_location_input, build_member_input, build_message_input, build_partner_request_input, build_profile_input, build_public_post_input, build_report_input, build_username_input
except ImportError:
    from application import (
        add_group_partner,
        block_user,
        comment_on_post,
        create_group_for_user,
        create_group_invite,
        create_public_post,
        delete_my_account,
        find_nearby_partners,
        follow_user,
        get_feed,
        get_current_user,
        get_current_user_dto,
        get_group_messages,
        get_my_profile,
        get_profile_visit_stats,
        join_group_by_invite,
        like_post,
        list_notifications,
        list_partner_requests,
        list_post_comments,
        list_my_groups,
        login_with_google,
        mark_user_active,
        read_notification,
        remove_group_partner,
        request_partner,
        respond_to_partner_request,
        revoke_invite,
        report_target,
        send_group_message,
        unblock_user,
        unfollow_user,
        unlike_post,
        update_my_location,
        update_my_profile,
        update_my_username,
        view_profile,
    )
    from database_adapter import init_db
    from models import AddGroupMemberDTO, BlockUserDTO, CommentInputDTO, CreateGroupDTO, CreateGroupInviteDTO, GoogleLoginDTO, LocationInputDTO, MessageInputDTO, PartnerRequestInputDTO, PartnerRequestStatus, ProfileInputDTO, PublicPostInputDTO, ReportInputDTO, TokenDTO, User, UsernameInputDTO
    from runtime_adapter import setup_environment, setup_logger
    from validation import build_block_input, build_comment_input, build_group_input, build_invite_input, build_location_input, build_member_input, build_message_input, build_partner_request_input, build_profile_input, build_public_post_input, build_report_input, build_username_input


app = FastAPI(title="partner_match_8", version="0.1.0")


# ============================================
# API boundary - thin wrapper around orchestration
# ============================================
@app.on_event("startup")
def startup() -> None:
    """Prepare runtime logging and database before serving requests."""
    log_file = setup_environment()
    setup_logger(log_file)
    init_db()


def _bad_request(error: Exception) -> HTTPException:
    """Convert app validation errors into user-friendly HTTP errors."""
    return HTTPException(status_code=400, detail=str(error))


def _auth_error(error: Exception) -> HTTPException:
    """Convert auth failures into user-friendly HTTP errors."""
    return HTTPException(status_code=401, detail=str(error))


def _extract_bearer_token(authorization: str | None) -> str:
    """Read a bearer token from the Authorization header."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Log in and send Authorization: Bearer <token>")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token is empty")
    return token


def _current_user(authorization: str | None) -> User:
    """Load the current user for protected endpoints."""
    try:
        return get_current_user(_extract_bearer_token(authorization))
    except ValueError as error:
        raise _auth_error(error) from error


def _profile_to_dict(profile) -> dict:
    """Convert a profile model into API-safe JSON."""
    return {
        "user_id": profile.user_id,
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


def _location_to_dict(location) -> dict:
    """Convert internal location state into current-user JSON."""
    return {
        "user_id": location.user_id,
        "latitude": location.latitude,
        "longitude": location.longitude,
        "city": location.city,
        "is_enabled": location.is_enabled,
        "updated_at": location.updated_at.isoformat(),
    }


def _nearby_to_dict(partner) -> dict:
    """Convert nearby partner output into API-safe JSON."""
    return {
        "user_id": partner.user_id,
        "display_name": partner.display_name,
        "bio": partner.bio,
        "mindset_tags": partner.mindset_tags,
        "goal_tags": partner.goal_tags,
        "sub_goal_tags": partner.sub_goal_tags,
        "looking_for": partner.looking_for,
        "availability": partner.availability.value,
        "verification": partner.verification.value,
        "presence": partner.presence.value,
        "distance_km": partner.distance_km,
        "distance_label": partner.distance_label,
        "city": partner.city,
        "avatar_url": partner.avatar_url,
    }


@app.get("/health")
def health() -> dict[str, str]:
    """Return a small liveness response."""
    return {"status": "ok"}


@app.post("/auth/google", response_model=TokenDTO)
def google_login(payload: GoogleLoginDTO) -> TokenDTO:
    """Log in with Google. Local MVP accepts dev:user@example.com as a fake token."""
    try:
        result = login_with_google(payload.id_token)
        return TokenDTO(access_token=result.access_token, expires_in_seconds=result.expires_in_seconds)
    except ValueError as error:
        raise _bad_request(error) from error


@app.get("/me")
def me(authorization: str | None = Header(default=None)) -> dict:
    """Return the current account."""
    try:
        return get_current_user_dto(_extract_bearer_token(authorization)).model_dump()
    except ValueError as error:
        raise _auth_error(error) from error


@app.post("/me/heartbeat")
def heartbeat(authorization: str | None = Header(default=None)) -> dict:
    """Refresh active status for the current user."""
    try:
        return mark_user_active(_current_user(authorization)).model_dump()
    except ValueError as error:
        raise _bad_request(error) from error


@app.put("/me/username")
def save_username(payload: UsernameInputDTO, authorization: str | None = Header(default=None)) -> dict:
    """Update the current user's unique username."""
    try:
        return update_my_username(_current_user(authorization), build_username_input(payload)).model_dump()
    except ValueError as error:
        raise _bad_request(error) from error


@app.delete("/me")
def delete_account(authorization: str | None = Header(default=None)) -> dict[str, str]:
    """Delete the current account."""
    try:
        return delete_my_account(_current_user(authorization))
    except ValueError as error:
        raise _bad_request(error) from error


@app.get("/me/profile")
def my_profile(authorization: str | None = Header(default=None)) -> dict:
    """Return the current user's partner profile."""
    return _profile_to_dict(get_my_profile(_current_user(authorization)))


@app.get("/profiles/{user_id}")
def public_profile(user_id: str, authorization: str | None = Header(default=None)) -> dict:
    """Return a public profile and record the visit."""
    try:
        return view_profile(_current_user(authorization), user_id)
    except ValueError as error:
        raise _bad_request(error) from error


@app.get("/me/profile-visits")
def profile_visits(authorization: str | None = Header(default=None)) -> dict[str, int]:
    """Return recent/weekly profile visit counts."""
    return get_profile_visit_stats(_current_user(authorization))


@app.put("/me/profile")
def save_profile(payload: ProfileInputDTO, authorization: str | None = Header(default=None)) -> dict:
    """Update the current user's partner profile."""
    try:
        profile = update_my_profile(_current_user(authorization), build_profile_input(payload))
        return _profile_to_dict(profile)
    except ValueError as error:
        raise _bad_request(error) from error


@app.put("/me/location")
def save_location(payload: LocationInputDTO, authorization: str | None = Header(default=None)) -> dict:
    """Update current user's opt-in location."""
    try:
        location = update_my_location(_current_user(authorization), build_location_input(payload))
        return _location_to_dict(location)
    except ValueError as error:
        raise _bad_request(error) from error


@app.get("/partners/nearby")
def nearby_partners(radius_km: float | None = None, authorization: str | None = Header(default=None)) -> list[dict]:
    """Find nearby opted-in partners."""
    try:
        partners = find_nearby_partners(_current_user(authorization), radius_km=radius_km)
        return [_nearby_to_dict(partner) for partner in partners]
    except ValueError as error:
        raise _bad_request(error) from error


@app.get("/feed")
def feed(limit: int = 50, authorization: str | None = Header(default=None)) -> list[dict]:
    """Return ranked shoutout/building feed posts."""
    return get_feed(_current_user(authorization), limit=limit)


@app.post("/posts")
def create_post(payload: PublicPostInputDTO, authorization: str | None = Header(default=None)) -> dict:
    """Create a public shoutout/building post."""
    try:
        return create_public_post(_current_user(authorization), build_public_post_input(payload))
    except ValueError as error:
        raise _bad_request(error) from error


@app.post("/posts/{post_id}/likes")
def post_like(post_id: str, authorization: str | None = Header(default=None)) -> dict:
    """Like a public post."""
    try:
        return like_post(_current_user(authorization), post_id)
    except ValueError as error:
        raise _bad_request(error) from error


@app.delete("/posts/{post_id}/likes")
def post_unlike(post_id: str, authorization: str | None = Header(default=None)) -> dict:
    """Unlike a public post."""
    return unlike_post(_current_user(authorization), post_id)


@app.post("/posts/{post_id}/comments")
def post_comment(post_id: str, payload: CommentInputDTO, authorization: str | None = Header(default=None)) -> dict:
    """Comment on a public post."""
    try:
        return comment_on_post(_current_user(authorization), post_id, build_comment_input(payload))
    except ValueError as error:
        raise _bad_request(error) from error


@app.get("/posts/{post_id}/comments")
def post_comments(post_id: str, limit: int = 50, authorization: str | None = Header(default=None)) -> list[dict]:
    """List comments on a public post."""
    try:
        return list_post_comments(_current_user(authorization), post_id, limit=limit)
    except ValueError as error:
        raise _bad_request(error) from error


@app.post("/users/{user_id}/follow")
def follow(user_id: str, authorization: str | None = Header(default=None)) -> dict:
    """Follow a user for updates."""
    try:
        return follow_user(_current_user(authorization), user_id)
    except ValueError as error:
        raise _bad_request(error) from error


@app.delete("/users/{user_id}/follow")
def unfollow(user_id: str, authorization: str | None = Header(default=None)) -> dict:
    """Unfollow a user."""
    return unfollow_user(_current_user(authorization), user_id)


@app.post("/groups")
def create_group(payload: CreateGroupDTO, authorization: str | None = Header(default=None)) -> dict:
    """Create a teammate group."""
    try:
        return create_group_for_user(_current_user(authorization), build_group_input(payload))
    except ValueError as error:
        raise _bad_request(error) from error


@app.get("/groups")
def groups(authorization: str | None = Header(default=None)) -> list[dict]:
    """List current user's groups."""
    return list_my_groups(_current_user(authorization))


@app.post("/groups/{group_id}/members")
def add_member(group_id: str, payload: AddGroupMemberDTO, authorization: str | None = Header(default=None)) -> dict:
    """Add a partner to a group."""
    try:
        clean = build_member_input(payload)
        return add_group_partner(_current_user(authorization), group_id, clean.partner_user_id)
    except ValueError as error:
        raise _bad_request(error) from error


@app.delete("/groups/{group_id}/members/{partner_user_id}")
def remove_member(group_id: str, partner_user_id: str, authorization: str | None = Header(default=None)) -> dict:
    """Remove a partner from a group."""
    try:
        return remove_group_partner(_current_user(authorization), group_id, partner_user_id)
    except ValueError as error:
        raise _bad_request(error) from error


@app.post("/groups/{group_id}/invites")
def create_invite(group_id: str, payload: CreateGroupInviteDTO, authorization: str | None = Header(default=None)) -> dict:
    """Create a group invite link."""
    try:
        return create_group_invite(_current_user(authorization), group_id, build_invite_input(payload))
    except ValueError as error:
        raise _bad_request(error) from error


@app.post("/groups/invites/{token}/join")
def join_invite(token: str, authorization: str | None = Header(default=None)) -> dict:
    """Join a group using an invite token."""
    try:
        return join_group_by_invite(_current_user(authorization), token)
    except ValueError as error:
        raise _bad_request(error) from error


@app.delete("/groups/invites/{token}")
def revoke_group_invite(token: str, authorization: str | None = Header(default=None)) -> dict[str, str]:
    """Revoke a group invite token."""
    try:
        return revoke_invite(_current_user(authorization), token)
    except ValueError as error:
        raise _bad_request(error) from error


@app.get("/groups/{group_id}/messages")
def messages(group_id: str, limit: int = 50, authorization: str | None = Header(default=None)) -> list[dict]:
    """Return group chat messages."""
    try:
        return get_group_messages(_current_user(authorization), group_id, limit=limit)
    except ValueError as error:
        raise _bad_request(error) from error


@app.post("/groups/{group_id}/messages")
def send_message(group_id: str, payload: MessageInputDTO, authorization: str | None = Header(default=None)) -> list[dict]:
    """Send a group chat message. Prefix with @agent to ask the AI teammate."""
    try:
        return send_group_message(_current_user(authorization), group_id, build_message_input(payload))
    except ValueError as error:
        raise _bad_request(error) from error


@app.post("/reports")
def report(payload: ReportInputDTO, authorization: str | None = Header(default=None)) -> dict:
    """Report a user, group, post, or comment."""
    try:
        return report_target(_current_user(authorization), build_report_input(payload))
    except ValueError as error:
        raise _bad_request(error) from error


@app.post("/partner-requests")
def create_partner_request(payload: PartnerRequestInputDTO, authorization: str | None = Header(default=None)) -> dict:
    """Request another user as a partner."""
    try:
        return request_partner(_current_user(authorization), build_partner_request_input(payload))
    except ValueError as error:
        raise _bad_request(error) from error


@app.get("/partner-requests")
def partner_requests(limit: int = 50, authorization: str | None = Header(default=None)) -> list[dict]:
    """List partner requests received by the current user."""
    return list_partner_requests(_current_user(authorization), limit=limit)


@app.post("/partner-requests/{request_id}/{status}")
def partner_request_response(request_id: str, status: PartnerRequestStatus, authorization: str | None = Header(default=None)) -> dict:
    """Accept or decline a partner request."""
    try:
        return respond_to_partner_request(_current_user(authorization), request_id, status)
    except ValueError as error:
        raise _bad_request(error) from error


@app.get("/notifications")
def notifications(limit: int = 50, authorization: str | None = Header(default=None)) -> list[dict]:
    """List general/message/partner-request notifications."""
    return list_notifications(_current_user(authorization), limit=limit)


@app.post("/notifications/{notification_id}/read")
def notification_read(notification_id: str, authorization: str | None = Header(default=None)) -> dict[str, bool]:
    """Mark one notification read."""
    return read_notification(_current_user(authorization), notification_id)


@app.post("/safety/blocks")
def block(payload: BlockUserDTO, authorization: str | None = Header(default=None)) -> dict[str, str]:
    """Block a user from matching/invite flows."""
    try:
        return block_user(_current_user(authorization), build_block_input(payload))
    except ValueError as error:
        raise _bad_request(error) from error


@app.delete("/safety/blocks/{blocked_user_id}")
def unblock(blocked_user_id: str, authorization: str | None = Header(default=None)) -> dict[str, str]:
    """Unblock a user."""
    try:
        return unblock_user(_current_user(authorization), blocked_user_id)
    except ValueError as error:
        raise _bad_request(error) from error
