"""Validation/parsing helpers for partner_match_8."""

try:
    from .models import AddGroupMemberDTO, BlockUserDTO, CommentInputDTO, CreateGroupDTO, CreateGroupInviteDTO, LocationInputDTO, MessageInputDTO, PartnerRequestInputDTO, ProfileInputDTO, PublicPostInputDTO, ReportInputDTO, UsernameInputDTO
except ImportError:
    from models import AddGroupMemberDTO, BlockUserDTO, CommentInputDTO, CreateGroupDTO, CreateGroupInviteDTO, LocationInputDTO, MessageInputDTO, PartnerRequestInputDTO, ProfileInputDTO, PublicPostInputDTO, ReportInputDTO, UsernameInputDTO


MAX_TAGS = 8
MAX_TAG_LENGTH = 32
MAX_MEDIA_URLS = 4
ALLOWED_GOAL_TAGS = {"fitness", "study", "programming", "business"}
ALLOWED_SUB_GOAL_TAGS = {
    "backend programming",
    "frontend programming",
    "mobile programming",
    "data science",
    "ai automation",
    "trading",
    "crypto",
    "sales",
    "marketing",
    "startup",
    "exam prep",
    "accountability",
    "strength training",
    "weight loss",
}


def _clean_text(value: str, field_name: str, *, max_length: int = 280, required: bool = True) -> str:
    """Normalize user text and reject empty/huge values early."""
    cleaned = value.strip() if isinstance(value, str) else ""
    if required and not cleaned:
        raise ValueError(f"{field_name} cannot be empty")
    if len(cleaned) > max_length:
        raise ValueError(f"{field_name} must be {max_length} characters or less")
    return cleaned


def _clean_tags(values: list[str], field_name: str) -> list[str]:
    """Normalize tags for matching."""
    cleaned: list[str] = []
    for value in values:
        tag = _clean_text(value, field_name, max_length=MAX_TAG_LENGTH, required=False).casefold()
        if tag and tag not in cleaned:
            cleaned.append(tag)
    if len(cleaned) > MAX_TAGS:
        raise ValueError(f"{field_name} accepts at most {MAX_TAGS} tags")
    return cleaned


def _clean_allowed_tags(values: list[str], field_name: str, allowed: set[str]) -> list[str]:
    """Normalize tags and reject values outside the product taxonomy."""
    cleaned = _clean_tags(values, field_name)
    unknown = [tag for tag in cleaned if tag not in allowed]
    if unknown:
        allowed_text = ", ".join(sorted(allowed))
        raise ValueError(f"{field_name} has unsupported tags: {', '.join(unknown)}. Use: {allowed_text}")
    return cleaned


def _clean_username(value: str) -> str:
    """Normalize username into a stable public handle."""
    cleaned = _clean_text(value, "username", max_length=30).casefold()
    if len(cleaned) < 3:
        raise ValueError("username must be at least 3 characters")
    if not all(char.isalnum() or char == "_" for char in cleaned):
        raise ValueError("username can only use letters, numbers, and underscores")
    return cleaned


def _clean_media_urls(values: list[str]) -> list[str]:
    """Validate lightweight media URLs for image/video posts."""
    cleaned: list[str] = []
    for value in values:
        url = _clean_text(value, "media_urls", max_length=500, required=False)
        if not url:
            continue
        if not url.startswith(("http://", "https://")):
            raise ValueError("media URLs must start with http:// or https://")
        if url not in cleaned:
            cleaned.append(url)
    if len(cleaned) > MAX_MEDIA_URLS:
        raise ValueError(f"media_urls accepts at most {MAX_MEDIA_URLS} URLs")
    return cleaned


def build_profile_input(payload: ProfileInputDTO) -> ProfileInputDTO:
    """Build clean profile input from raw HTTP payload."""
    return ProfileInputDTO(
        display_name=_clean_text(payload.display_name, "display_name", max_length=80),
        bio=_clean_text(payload.bio, "bio", max_length=500, required=False),
        mindset_tags=_clean_tags(payload.mindset_tags, "mindset_tags"),
        goal_tags=_clean_allowed_tags(payload.goal_tags, "goal_tags", ALLOWED_GOAL_TAGS),
        sub_goal_tags=_clean_allowed_tags(payload.sub_goal_tags, "sub_goal_tags", ALLOWED_SUB_GOAL_TAGS),
        looking_for=_clean_text(payload.looking_for, "looking_for", max_length=220, required=False),
        availability=payload.availability,
    )


def build_username_input(payload: UsernameInputDTO) -> UsernameInputDTO:
    """Validate username update input."""
    return UsernameInputDTO(username=_clean_username(payload.username))


def build_location_input(payload: LocationInputDTO) -> LocationInputDTO:
    """Validate opt-in coordinates from the client."""
    if not -90 <= payload.latitude <= 90:
        raise ValueError("latitude must be between -90 and 90")
    if not -180 <= payload.longitude <= 180:
        raise ValueError("longitude must be between -180 and 180")
    return LocationInputDTO(
        latitude=payload.latitude,
        longitude=payload.longitude,
        city=_clean_text(payload.city or "", "city", max_length=80, required=False) or None,
        is_enabled=payload.is_enabled,
    )


def build_group_input(payload: CreateGroupDTO) -> CreateGroupDTO:
    """Validate group creation input."""
    return CreateGroupDTO(
        name=_clean_text(payload.name, "name", max_length=80),
        purpose=_clean_text(payload.purpose, "purpose", max_length=280, required=False),
    )


def build_member_input(payload: AddGroupMemberDTO) -> AddGroupMemberDTO:
    """Validate group member input."""
    return AddGroupMemberDTO(partner_user_id=_clean_text(payload.partner_user_id, "partner_user_id", max_length=80))


def build_invite_input(payload: CreateGroupInviteDTO) -> CreateGroupInviteDTO:
    """Validate group invite creation input."""
    if payload.expires_in_hours is None:
        return CreateGroupInviteDTO(expires_in_hours=None)
    if not 1 <= payload.expires_in_hours <= 720:
        raise ValueError("expires_in_hours must be between 1 and 720")
    return CreateGroupInviteDTO(expires_in_hours=payload.expires_in_hours)


def build_message_input(payload: MessageInputDTO) -> MessageInputDTO:
    """Validate chat message input."""
    return MessageInputDTO(body=_clean_text(payload.body, "body", max_length=1200))


def build_public_post_input(payload: PublicPostInputDTO) -> PublicPostInputDTO:
    """Validate public feed post input."""
    return PublicPostInputDTO(
        post_type=payload.post_type,
        body=_clean_text(payload.body, "body", max_length=2000),
        media_urls=_clean_media_urls(payload.media_urls),
        tags=_clean_tags(payload.tags, "tags"),
    )


def build_comment_input(payload: CommentInputDTO) -> CommentInputDTO:
    """Validate post-comment input."""
    return CommentInputDTO(body=_clean_text(payload.body, "body", max_length=600))


def build_partner_request_input(payload: PartnerRequestInputDTO) -> PartnerRequestInputDTO:
    """Validate one-to-one partner request input."""
    return PartnerRequestInputDTO(
        receiver_user_id=_clean_text(payload.receiver_user_id, "receiver_user_id", max_length=80),
        message=_clean_text(payload.message or "", "message", max_length=300, required=False) or None,
    )


def build_report_input(payload: ReportInputDTO) -> ReportInputDTO:
    """Validate report input."""
    return ReportInputDTO(
        target_type=payload.target_type,
        target_id=_clean_text(payload.target_id, "target_id", max_length=80),
        reason=_clean_text(payload.reason, "reason", max_length=120),
        details=_clean_text(payload.details or "", "details", max_length=1000, required=False) or None,
    )


def build_block_input(payload: BlockUserDTO) -> BlockUserDTO:
    """Validate block-user input."""
    return BlockUserDTO(blocked_user_id=_clean_text(payload.blocked_user_id, "blocked_user_id", max_length=80))
