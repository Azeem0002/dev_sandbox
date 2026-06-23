"""Core models for partner_match_8.

This app is a broader NearSpace-style partner locator: users opt into location,
find nearby people with matching mindset/goals, and form small teammate groups.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class PresenceStatus(StrEnum):
    """Public activity state shown to other partners."""
    ONLINE = "online"
    RECENTLY_ACTIVE = "recently_active"
    OFFLINE = "offline"


class AvailabilityStatus(StrEnum):
    """Whether a user wants new partner/team requests."""
    OPEN_TO_PARTNER = "open_to_partner"
    BUSY = "busy"
    NOT_LOOKING = "not_looking"


class VerificationStatus(StrEnum):
    """Public verification badge state."""
    UNVERIFIED = "unverified"
    VERIFIED = "verified"


class GroupRole(StrEnum):
    """Role inside a partner group."""
    ADMIN = "admin"
    PARTNER = "partner"
    AI_AGENT = "ai_agent"


class ReportTargetType(StrEnum):
    """Thing a user can report."""
    USER = "user"
    GROUP = "group"
    POST = "post"
    COMMENT = "comment"


class MessageSenderType(StrEnum):
    """Who produced a group-chat message."""
    USER = "user"
    AI_AGENT = "ai_agent"


class PostType(StrEnum):
    """Feed lane for public posts."""
    SHOUTOUT = "shoutout"
    BUILDING = "building"


class NotificationType(StrEnum):
    """Notification lanes shown in the app."""
    GENERAL = "general"
    MESSAGE = "message"
    PARTNER_REQUEST = "partner_request"


class PartnerRequestStatus(StrEnum):
    """State of a one-to-one partner request."""
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"


@dataclass(frozen=True)
class AppConfig:
    """Runtime limits that should not be hardcoded inside business logic."""
    max_group_members: int = 5
    online_window_seconds: int = 300
    recently_active_window_seconds: int = 86400
    default_radius_km: float = 25.0


@dataclass(frozen=True)
class GoogleIdentity:
    """Verified Google identity returned by the auth adapter."""
    google_sub: str
    email: str
    display_name: str
    avatar_url: str | None = None


@dataclass
class User:
    """Internal user account."""
    id: str
    email: str
    google_sub: str
    username: str
    display_name: str
    avatar_url: str | None
    is_verified: bool
    created_at: datetime
    last_seen_at: datetime
    deleted_at: datetime | None = None


@dataclass
class AuthSession:
    """Server-side session record tied to one JWT token id."""
    id: str
    user_id: str
    token_id: str
    expires_at: datetime
    revoked_at: datetime | None = None


@dataclass
class AuthResult:
    """Application result after successful Google login."""
    user: User
    session: AuthSession
    access_token: str
    expires_in_seconds: int


@dataclass
class PartnerProfile:
    """Public partner profile used for matching."""
    user_id: str
    display_name: str
    bio: str
    mindset_tags: list[str]
    goal_tags: list[str]
    sub_goal_tags: list[str]
    looking_for: str
    availability: AvailabilityStatus = AvailabilityStatus.OPEN_TO_PARTNER
    verification: VerificationStatus = VerificationStatus.UNVERIFIED
    avatar_url: str | None = None


@dataclass
class PartnerLocation:
    """Opt-in location state. Exact coordinates are never returned by public endpoints."""
    user_id: str
    latitude: float
    longitude: float
    city: str | None
    is_enabled: bool
    updated_at: datetime


@dataclass
class NearbyPartner:
    """Nearby partner result with coarse distance only."""
    user_id: str
    display_name: str
    bio: str
    mindset_tags: list[str]
    goal_tags: list[str]
    sub_goal_tags: list[str]
    looking_for: str
    availability: AvailabilityStatus
    verification: VerificationStatus
    presence: PresenceStatus
    distance_km: float
    distance_label: str
    city: str | None
    avatar_url: str | None = None


@dataclass
class PartnerGroup:
    """Small teammate group controlled by an admin."""
    id: str
    name: str
    purpose: str
    admin_user_id: str
    created_at: datetime


@dataclass
class GroupMember:
    """One user membership inside a group."""
    group_id: str
    user_id: str
    role: GroupRole
    joined_at: datetime


@dataclass
class GroupInvite:
    """Join link for adding partners to a group."""
    id: str
    group_id: str
    token: str
    created_by_user_id: str
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


@dataclass
class ChatMessage:
    """One group chat message."""
    id: str
    group_id: str
    sender_id: str | None
    sender_type: MessageSenderType
    body: str
    created_at: datetime


@dataclass
class MemberReport:
    """Abuse/safety report for a user or group."""
    id: str
    reporter_user_id: str
    target_type: ReportTargetType
    target_id: str
    reason: str
    details: str | None
    created_at: datetime


@dataclass
class SafetyBlock:
    """One user blocking another user inside the app."""
    blocker_user_id: str
    blocked_user_id: str
    created_at: datetime


@dataclass
class PublicPost:
    """Public feed post created by a user."""
    id: str
    author_user_id: str
    post_type: PostType
    body: str
    media_urls: list[str]
    tags: list[str]
    created_at: datetime


@dataclass
class PostComment:
    """Comment on a public feed post."""
    id: str
    post_id: str
    author_user_id: str
    body: str
    created_at: datetime


@dataclass
class Notification:
    """In-app notification for general, message, or partner-request events."""
    id: str
    user_id: str
    notification_type: NotificationType
    title: str
    body: str
    related_id: str | None
    read_at: datetime | None
    created_at: datetime


@dataclass
class PartnerRequest:
    """One user asking another user to connect as partners."""
    id: str
    requester_user_id: str
    receiver_user_id: str
    status: PartnerRequestStatus
    message: str | None
    created_at: datetime
    responded_at: datetime | None = None


class GoogleLoginDTO(BaseModel):
    """HTTP input for Google login."""
    id_token: str


class TokenDTO(BaseModel):
    """HTTP output containing a bearer access token."""
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int


class UserDTO(BaseModel):
    """HTTP-safe user output."""
    id: str
    email: str
    username: str
    display_name: str
    avatar_url: str | None = None
    verification: VerificationStatus
    presence: PresenceStatus


class ProfileInputDTO(BaseModel):
    """HTTP input for partner profile updates."""
    display_name: str
    bio: str = ""
    mindset_tags: list[str] = Field(default_factory=list)
    goal_tags: list[str] = Field(default_factory=list)
    sub_goal_tags: list[str] = Field(default_factory=list)
    looking_for: str = ""
    availability: AvailabilityStatus = AvailabilityStatus.OPEN_TO_PARTNER


class UsernameInputDTO(BaseModel):
    """HTTP input for changing username."""
    username: str


class LocationInputDTO(BaseModel):
    """HTTP input for opt-in location updates."""
    latitude: float
    longitude: float
    city: str | None = None
    is_enabled: bool = True


class CreateGroupDTO(BaseModel):
    """HTTP input for creating a teammate group."""
    name: str
    purpose: str = ""


class AddGroupMemberDTO(BaseModel):
    """HTTP input for adding a partner to a group."""
    partner_user_id: str


class CreateGroupInviteDTO(BaseModel):
    """HTTP input for creating a group invite link."""
    expires_in_hours: int | None = 72


class MessageInputDTO(BaseModel):
    """HTTP input for sending a group chat message."""
    body: str


class PublicPostInputDTO(BaseModel):
    """HTTP input for creating a public post."""
    post_type: PostType = PostType.SHOUTOUT
    body: str
    media_urls: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class CommentInputDTO(BaseModel):
    """HTTP input for commenting on a post."""
    body: str


class PartnerRequestInputDTO(BaseModel):
    """HTTP input for requesting a user as a partner."""
    receiver_user_id: str
    message: str | None = None


class ReportInputDTO(BaseModel):
    """HTTP input for reporting a user or group."""
    target_type: ReportTargetType
    target_id: str
    reason: str
    details: str | None = None


class BlockUserDTO(BaseModel):
    """HTTP input for blocking a user."""
    blocked_user_id: str


APP_CONFIG = AppConfig()
