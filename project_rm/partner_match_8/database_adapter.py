#!/usr/bin/env python3
"""SQLite database adapter for partner_match_8."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

try:
    from .models import (
        AuthSession,
        AvailabilityStatus,
        ChatMessage,
        GoogleIdentity,
        GroupMember,
        GroupInvite,
        GroupRole,
        MemberReport,
        MessageSenderType,
        Notification,
        NotificationType,
        PartnerGroup,
        PartnerLocation,
        PartnerProfile,
        PartnerRequest,
        PartnerRequestStatus,
        PostComment,
        PostType,
        PublicPost,
        ReportTargetType,
        SafetyBlock,
        User,
        VerificationStatus,
    )
    from .runtime_adapter import get_platform_dirs
except ImportError:
    from models import (
        AuthSession,
        AvailabilityStatus,
        ChatMessage,
        GoogleIdentity,
        GroupMember,
        GroupInvite,
        GroupRole,
        MemberReport,
        MessageSenderType,
        Notification,
        NotificationType,
        PartnerGroup,
        PartnerLocation,
        PartnerProfile,
        PartnerRequest,
        PartnerRequestStatus,
        PostComment,
        PostType,
        PublicPost,
        ReportTargetType,
        SafetyBlock,
        User,
        VerificationStatus,
    )
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
    return Path(dirs.user_data_dir) / "partner_match.db"


DB_PATH = _get_db_path()


def _utc_now_iso() -> str:
    """Return current UTC time serialized for SQLite."""
    return datetime.now(timezone.utc).isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse stored ISO datetime text into datetime."""
    return datetime.fromisoformat(value) if value else None


def _connect() -> sqlite3.Connection:
    """Open one SQLite connection with row access and pragmatic defaults."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def _init_db() -> None:
    """Initialize database schema and indexes."""
    # Init is the explicit setup step, so parent-dir creation belongs here.
    DB_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            google_sub TEXT NOT NULL UNIQUE,
            username TEXT,
            display_name TEXT NOT NULL,
            avatar_url TEXT,
            is_verified INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            deleted_at TEXT
        )
        """)
        _add_column_if_missing(conn, "users", "username", "TEXT")
        conn.execute("UPDATE users SET username = LOWER(REPLACE(REPLACE(email, '@', '_'), '.', '_')) WHERE username IS NULL")
        _add_column_if_missing(conn, "users", "is_verified", "INTEGER NOT NULL DEFAULT 0")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_google_sub ON users(google_sub)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username)")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            token_id TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            revoked_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_token_id ON sessions(token_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            user_id TEXT PRIMARY KEY,
            bio TEXT NOT NULL,
            mindset_tags_json TEXT NOT NULL,
            goal_tags_json TEXT NOT NULL,
            sub_goal_tags_json TEXT NOT NULL DEFAULT '[]',
            looking_for TEXT NOT NULL,
            availability_status TEXT NOT NULL DEFAULT 'open_to_partner',
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """)
        _add_column_if_missing(conn, "profiles", "sub_goal_tags_json", "TEXT NOT NULL DEFAULT '[]'")
        _add_column_if_missing(conn, "profiles", "availability_status", "TEXT NOT NULL DEFAULT 'open_to_partner'")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS locations (
            user_id TEXT PRIMARY KEY,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            city TEXT,
            is_enabled INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_locations_enabled ON locations(is_enabled)")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            purpose TEXT NOT NULL,
            admin_user_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            deleted_at TEXT,
            FOREIGN KEY(admin_user_id) REFERENCES users(id)
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_groups_admin ON groups(admin_user_id)")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS group_members (
            group_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            joined_at TEXT NOT NULL,
            PRIMARY KEY(group_id, user_id),
            FOREIGN KEY(group_id) REFERENCES groups(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_group_members_user_id ON group_members(user_id)")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS group_invites (
            id TEXT PRIMARY KEY,
            group_id TEXT NOT NULL,
            token TEXT NOT NULL UNIQUE,
            created_by_user_id TEXT NOT NULL,
            expires_at TEXT,
            revoked_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(group_id) REFERENCES groups(id),
            FOREIGN KEY(created_by_user_id) REFERENCES users(id)
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_group_invites_token ON group_invites(token)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_group_invites_group_id ON group_invites(group_id)")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            group_id TEXT NOT NULL,
            sender_id TEXT,
            sender_type TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(group_id) REFERENCES groups(id),
            FOREIGN KEY(sender_id) REFERENCES users(id)
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_group_time ON messages(group_id, created_at)")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id TEXT PRIMARY KEY,
            reporter_user_id TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            details TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(reporter_user_id) REFERENCES users(id)
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_target ON reports(target_type, target_id)")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS safety_blocks (
            blocker_user_id TEXT NOT NULL,
            blocked_user_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(blocker_user_id, blocked_user_id),
            FOREIGN KEY(blocker_user_id) REFERENCES users(id),
            FOREIGN KEY(blocked_user_id) REFERENCES users(id)
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_safety_blocks_blocked ON safety_blocks(blocked_user_id)")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id TEXT PRIMARY KEY,
            author_user_id TEXT NOT NULL,
            post_type TEXT NOT NULL,
            body TEXT NOT NULL,
            media_urls_json TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            deleted_at TEXT,
            FOREIGN KEY(author_user_id) REFERENCES users(id)
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_author ON posts(author_user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_created_at ON posts(created_at)")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS post_likes (
            post_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(post_id, user_id),
            FOREIGN KEY(post_id) REFERENCES posts(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS post_comments (
            id TEXT PRIMARY KEY,
            post_id TEXT NOT NULL,
            author_user_id TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL,
            deleted_at TEXT,
            FOREIGN KEY(post_id) REFERENCES posts(id),
            FOREIGN KEY(author_user_id) REFERENCES users(id)
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_post_comments_post_id ON post_comments(post_id)")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS follows (
            follower_user_id TEXT NOT NULL,
            followed_user_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(follower_user_id, followed_user_id),
            FOREIGN KEY(follower_user_id) REFERENCES users(id),
            FOREIGN KEY(followed_user_id) REFERENCES users(id)
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_follows_followed ON follows(followed_user_id)")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS partner_requests (
            id TEXT PRIMARY KEY,
            requester_user_id TEXT NOT NULL,
            receiver_user_id TEXT NOT NULL,
            status TEXT NOT NULL,
            message TEXT,
            created_at TEXT NOT NULL,
            responded_at TEXT,
            UNIQUE(requester_user_id, receiver_user_id),
            FOREIGN KEY(requester_user_id) REFERENCES users(id),
            FOREIGN KEY(receiver_user_id) REFERENCES users(id)
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_partner_requests_receiver ON partner_requests(receiver_user_id, status)")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            notification_type TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            related_id TEXT,
            read_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user_time ON notifications(user_id, created_at)")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS profile_visits (
            visitor_user_id TEXT NOT NULL,
            visited_user_id TEXT NOT NULL,
            visited_at TEXT NOT NULL,
            FOREIGN KEY(visitor_user_id) REFERENCES users(id),
            FOREIGN KEY(visited_user_id) REFERENCES users(id)
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_profile_visits_visited_time ON profile_visits(visited_user_id, visited_at)")
        logger.debug("Partner match database initialized")


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    """Add one SQLite column only when an older local MVP database is missing it."""
    # MVP schemas change while you are learning and iterating.
    # This tiny migration helper lets old local databases keep working after a new column is added.
    conn.row_factory = sqlite3.Row
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _row_to_user(row: sqlite3.Row | None) -> User | None:
    """Map one SQLite user row into an internal user model."""
    if row is None:
        return None
    return User(
        id=row["id"],
        email=row["email"],
        google_sub=row["google_sub"],
        username=row["username"],
        display_name=row["display_name"],
        avatar_url=row["avatar_url"],
        is_verified=bool(row["is_verified"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
        deleted_at=_parse_datetime(row["deleted_at"]),
    )


def _row_to_session(row: sqlite3.Row | None) -> AuthSession | None:
    """Map one SQLite session row into an internal session model."""
    if row is None:
        return None
    return AuthSession(
        id=row["id"],
        user_id=row["user_id"],
        token_id=row["token_id"],
        expires_at=datetime.fromisoformat(row["expires_at"]),
        revoked_at=_parse_datetime(row["revoked_at"]),
    )


def _row_to_profile(row: sqlite3.Row | None, user: User) -> PartnerProfile | None:
    """Map one SQLite profile row into a public profile model."""
    if row is None:
        return None
    return PartnerProfile(
        user_id=user.id,
        display_name=user.display_name,
        bio=row["bio"],
        mindset_tags=json.loads(row["mindset_tags_json"]),
        goal_tags=json.loads(row["goal_tags_json"]),
        sub_goal_tags=json.loads(row["sub_goal_tags_json"]),
        looking_for=row["looking_for"],
        availability=AvailabilityStatus(row["availability_status"]),
        verification=VerificationStatus.VERIFIED if user.is_verified else VerificationStatus.UNVERIFIED,
        avatar_url=user.avatar_url,
    )


def _row_to_location(row: sqlite3.Row | None) -> PartnerLocation | None:
    """Map one SQLite location row into an internal location model."""
    if row is None:
        return None
    return PartnerLocation(
        user_id=row["user_id"],
        latitude=float(row["latitude"]),
        longitude=float(row["longitude"]),
        city=row["city"],
        is_enabled=bool(row["is_enabled"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _row_to_group(row: sqlite3.Row | None) -> PartnerGroup | None:
    """Map one SQLite group row into an internal group model."""
    if row is None:
        return None
    return PartnerGroup(
        id=row["id"],
        name=row["name"],
        purpose=row["purpose"],
        admin_user_id=row["admin_user_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _row_to_group_member(row: sqlite3.Row | None) -> GroupMember | None:
    """Map one SQLite group-member row into an internal membership model."""
    if row is None:
        return None
    return GroupMember(
        group_id=row["group_id"],
        user_id=row["user_id"],
        role=GroupRole(row["role"]),
        joined_at=datetime.fromisoformat(row["joined_at"]),
    )


def _row_to_group_invite(row: sqlite3.Row | None) -> GroupInvite | None:
    """Map one SQLite invite row into an internal invite model."""
    if row is None:
        return None
    return GroupInvite(
        id=row["id"],
        group_id=row["group_id"],
        token=row["token"],
        created_by_user_id=row["created_by_user_id"],
        expires_at=_parse_datetime(row["expires_at"]),
        revoked_at=_parse_datetime(row["revoked_at"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _row_to_message(row: sqlite3.Row | None) -> ChatMessage | None:
    """Map one SQLite message row into an internal chat message model."""
    if row is None:
        return None
    return ChatMessage(
        id=row["id"],
        group_id=row["group_id"],
        sender_id=row["sender_id"],
        sender_type=MessageSenderType(row["sender_type"]),
        body=row["body"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _row_to_report(row: sqlite3.Row | None) -> MemberReport | None:
    """Map one SQLite report row into an internal report model."""
    if row is None:
        return None
    return MemberReport(
        id=row["id"],
        reporter_user_id=row["reporter_user_id"],
        target_type=ReportTargetType(row["target_type"]),
        target_id=row["target_id"],
        reason=row["reason"],
        details=row["details"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _row_to_public_post(row: sqlite3.Row | None) -> PublicPost | None:
    """Map one SQLite post row into an internal public-post model."""
    if row is None:
        return None
    return PublicPost(
        id=row["id"],
        author_user_id=row["author_user_id"],
        post_type=PostType(row["post_type"]),
        body=row["body"],
        media_urls=json.loads(row["media_urls_json"]),
        tags=json.loads(row["tags_json"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _row_to_post_comment(row: sqlite3.Row | None) -> PostComment | None:
    """Map one SQLite comment row into an internal post-comment model."""
    if row is None:
        return None
    return PostComment(
        id=row["id"],
        post_id=row["post_id"],
        author_user_id=row["author_user_id"],
        body=row["body"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _row_to_notification(row: sqlite3.Row | None) -> Notification | None:
    """Map one SQLite notification row into an internal notification model."""
    if row is None:
        return None
    return Notification(
        id=row["id"],
        user_id=row["user_id"],
        notification_type=NotificationType(row["notification_type"]),
        title=row["title"],
        body=row["body"],
        related_id=row["related_id"],
        read_at=_parse_datetime(row["read_at"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _row_to_partner_request(row: sqlite3.Row | None) -> PartnerRequest | None:
    """Map one SQLite partner-request row into an internal request model."""
    if row is None:
        return None
    return PartnerRequest(
        id=row["id"],
        requester_user_id=row["requester_user_id"],
        receiver_user_id=row["receiver_user_id"],
        status=PartnerRequestStatus(row["status"]),
        message=row["message"],
        created_at=datetime.fromisoformat(row["created_at"]),
        responded_at=_parse_datetime(row["responded_at"]),
    )


def _is_verified_email(email: str) -> bool:
    """Return whether this email should receive the MVP verification badge."""
    import os

    verified = {item.strip().lower() for item in os.getenv("PARTNER_MATCH_VERIFIED_EMAILS", "").split(",") if item.strip()}
    return email.lower() in verified


@retry(retry=retry_if_exception_type(sqlite3.OperationalError), stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5), reraise=True)
def _upsert_user_from_google(identity: GoogleIdentity, now: datetime) -> User:
    """Create or update one Google-backed user account."""
    user_id = f"user_{identity.google_sub.replace(':', '_').replace('@', '_')}"
    is_verified = _is_verified_email(identity.email)
    with _connect() as conn:
        username = _build_available_username(conn, identity.email.split("@", 1)[0])
        conn.execute(
            """
            INSERT INTO users (id, email, google_sub, username, display_name, avatar_url, is_verified, created_at, last_seen_at, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(google_sub) DO UPDATE SET
                email = excluded.email,
                display_name = excluded.display_name,
                avatar_url = excluded.avatar_url,
                is_verified = MAX(users.is_verified, excluded.is_verified),
                last_seen_at = excluded.last_seen_at,
                deleted_at = NULL
            """,
            (user_id, identity.email, identity.google_sub, username, identity.display_name, identity.avatar_url, int(is_verified), now.isoformat(), now.isoformat()),
        )
        row = conn.execute("SELECT * FROM users WHERE google_sub = ?", (identity.google_sub,)).fetchone()
    user = _row_to_user(row)
    if user is None:
        raise RuntimeError("Failed to load Google user after upsert")
    return user


def _build_available_username(conn: sqlite3.Connection, seed: str) -> str:
    """Build a username and add a short suffix only when the preferred one is taken."""
    base = "".join(char if char.isalnum() or char == "_" else "_" for char in seed.casefold()).strip("_") or "partner"
    base = base[:24]
    candidate = base
    counter = 2
    while conn.execute("SELECT 1 FROM users WHERE username = ?", (candidate,)).fetchone() is not None:
        candidate = f"{base}_{counter}"
        counter += 1
    return candidate


def _update_username(user_id: str, username: str) -> User:
    """Update one user's public username."""
    with _connect() as conn:
        try:
            conn.execute("UPDATE users SET username = ? WHERE id = ? AND deleted_at IS NULL", (username, user_id))
        except sqlite3.IntegrityError as error:
            raise ValueError("Username is already taken") from error
        row = conn.execute("SELECT * FROM users WHERE id = ? AND deleted_at IS NULL", (user_id,)).fetchone()
    user = _row_to_user(row)
    if user is None:
        raise ValueError("Account is no longer available")
    return user


def _fetch_user_by_id(user_id: str) -> User | None:
    """Fetch one active user by id."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ? AND deleted_at IS NULL", (user_id,)).fetchone()
    return _row_to_user(row)


def _touch_user_seen(user_id: str, now: datetime) -> User | None:
    """Refresh last-seen time for an active user."""
    with _connect() as conn:
        conn.execute("UPDATE users SET last_seen_at = ? WHERE id = ? AND deleted_at IS NULL", (now.isoformat(), user_id))
        row = conn.execute("SELECT * FROM users WHERE id = ? AND deleted_at IS NULL", (user_id,)).fetchone()
    return _row_to_user(row)


def _soft_delete_user(user_id: str, now: datetime) -> bool:
    """Soft-delete one user and hide their location."""
    with _connect() as conn:
        cursor = conn.execute("UPDATE users SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL", (now.isoformat(), user_id))
        conn.execute("UPDATE locations SET is_enabled = 0, updated_at = ? WHERE user_id = ?", (now.isoformat(), user_id))
        conn.execute("UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL", (now.isoformat(), user_id))
    return cursor.rowcount > 0


def _insert_session(session: AuthSession) -> AuthSession:
    """Insert one auth session."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO sessions (id, user_id, token_id, expires_at, revoked_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session.id, session.user_id, session.token_id, session.expires_at.isoformat(), session.revoked_at.isoformat() if session.revoked_at else None, _utc_now_iso()),
        )
    return session


def _fetch_session_by_token_id(token_id: str) -> AuthSession | None:
    """Fetch a session by JWT token id."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE token_id = ?", (token_id,)).fetchone()
    return _row_to_session(row)


def _upsert_profile(profile: PartnerProfile) -> PartnerProfile:
    """Create or update one partner profile."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO profiles (user_id, bio, mindset_tags_json, goal_tags_json, sub_goal_tags_json, looking_for, availability_status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                bio = excluded.bio,
                mindset_tags_json = excluded.mindset_tags_json,
                goal_tags_json = excluded.goal_tags_json,
                sub_goal_tags_json = excluded.sub_goal_tags_json,
                looking_for = excluded.looking_for,
                availability_status = excluded.availability_status,
                updated_at = excluded.updated_at
            """,
            (
                profile.user_id,
                profile.bio,
                json.dumps(profile.mindset_tags),
                json.dumps(profile.goal_tags),
                json.dumps(profile.sub_goal_tags),
                profile.looking_for,
                profile.availability.value,
                _utc_now_iso(),
            ),
        )
        conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (profile.display_name, profile.user_id))
    return profile


def _fetch_profile(user_id: str) -> PartnerProfile | None:
    """Fetch one partner profile by user id."""
    with _connect() as conn:
        user_row = conn.execute("SELECT * FROM users WHERE id = ? AND deleted_at IS NULL", (user_id,)).fetchone()
        profile_row = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
    user = _row_to_user(user_row)
    return _row_to_profile(profile_row, user) if user else None


def _upsert_location(location: PartnerLocation) -> PartnerLocation:
    """Create or update one opt-in location row."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO locations (user_id, latitude, longitude, city, is_enabled, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                latitude = excluded.latitude,
                longitude = excluded.longitude,
                city = excluded.city,
                is_enabled = excluded.is_enabled,
                updated_at = excluded.updated_at
            """,
            (location.user_id, location.latitude, location.longitude, location.city, int(location.is_enabled), location.updated_at.isoformat()),
        )
    return location


def _fetch_location(user_id: str) -> PartnerLocation | None:
    """Fetch one user's current location state."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM locations WHERE user_id = ?", (user_id,)).fetchone()
    return _row_to_location(row)


def _fetch_location_candidates(exclude_user_id: str) -> list[tuple[User, PartnerProfile | None, PartnerLocation]]:
    """Fetch active opt-in users who may be returned by nearby search."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                users.*,
                profiles.bio,
                profiles.mindset_tags_json,
                profiles.goal_tags_json,
                profiles.sub_goal_tags_json,
                profiles.looking_for,
                profiles.availability_status,
                locations.latitude,
                locations.longitude,
                locations.city,
                locations.is_enabled,
                locations.updated_at AS location_updated_at
            FROM users
            JOIN locations ON users.id = locations.user_id
            LEFT JOIN profiles ON users.id = profiles.user_id
            WHERE users.id != ?
              AND users.deleted_at IS NULL
              AND locations.is_enabled = 1
            """,
            (exclude_user_id,),
        ).fetchall()

    candidates: list[tuple[User, PartnerProfile | None, PartnerLocation]] = []
    for row in rows:
        user = _row_to_user(row)
        if user is None:
            continue
        profile = PartnerProfile(
            user_id=user.id,
            display_name=user.display_name,
            bio=row["bio"] or "",
            mindset_tags=json.loads(row["mindset_tags_json"] or "[]"),
            goal_tags=json.loads(row["goal_tags_json"] or "[]"),
            sub_goal_tags=json.loads(row["sub_goal_tags_json"] or "[]"),
            looking_for=row["looking_for"] or "",
            availability=AvailabilityStatus(row["availability_status"] or "open_to_partner"),
            verification=VerificationStatus.VERIFIED if user.is_verified else VerificationStatus.UNVERIFIED,
            avatar_url=user.avatar_url,
        )
        location = PartnerLocation(
            user_id=user.id,
            latitude=float(row["latitude"]),
            longitude=float(row["longitude"]),
            city=row["city"],
            is_enabled=bool(row["is_enabled"]),
            updated_at=datetime.fromisoformat(row["location_updated_at"]),
        )
        candidates.append((user, profile, location))
    return candidates


def _insert_group(group: PartnerGroup, admin_member: GroupMember) -> PartnerGroup:
    """Create one group and add the creator as admin."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO groups (id, name, purpose, admin_user_id, created_at, deleted_at) VALUES (?, ?, ?, ?, ?, NULL)",
            (group.id, group.name, group.purpose, group.admin_user_id, group.created_at.isoformat()),
        )
        conn.execute(
            "INSERT INTO group_members (group_id, user_id, role, joined_at) VALUES (?, ?, ?, ?)",
            (admin_member.group_id, admin_member.user_id, admin_member.role.value, admin_member.joined_at.isoformat()),
        )
    return group


def _fetch_group(group_id: str) -> PartnerGroup | None:
    """Fetch one active group by id."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM groups WHERE id = ? AND deleted_at IS NULL", (group_id,)).fetchone()
    return _row_to_group(row)


def _fetch_user_groups(user_id: str) -> list[PartnerGroup]:
    """Fetch groups where one user is a member."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT groups.*
            FROM groups
            JOIN group_members ON groups.id = group_members.group_id
            WHERE group_members.user_id = ?
              AND groups.deleted_at IS NULL
            ORDER BY groups.created_at DESC
            """,
            (user_id,),
        ).fetchall()
    return [group for row in rows if (group := _row_to_group(row)) is not None]


def _count_group_members(group_id: str) -> int:
    """Count active members in one group."""
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS total FROM group_members WHERE group_id = ?", (group_id,)).fetchone()
    return int(row["total"])


def _fetch_group_member(group_id: str, user_id: str) -> GroupMember | None:
    """Fetch one membership row."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM group_members WHERE group_id = ? AND user_id = ?", (group_id, user_id)).fetchone()
    return _row_to_group_member(row)


def _fetch_group_members(group_id: str) -> list[GroupMember]:
    """Fetch all members of one group."""
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM group_members WHERE group_id = ? ORDER BY joined_at", (group_id,)).fetchall()
    return [member for row in rows if (member := _row_to_group_member(row)) is not None]


def _insert_group_member(member: GroupMember) -> GroupMember:
    """Add one partner to a group."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO group_members (group_id, user_id, role, joined_at) VALUES (?, ?, ?, ?)",
            (member.group_id, member.user_id, member.role.value, member.joined_at.isoformat()),
        )
    return member


def _delete_group_member(group_id: str, user_id: str) -> bool:
    """Remove one partner from a group."""
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM group_members WHERE group_id = ? AND user_id = ?", (group_id, user_id))
    return cursor.rowcount > 0


def _insert_group_invite(invite: GroupInvite) -> GroupInvite:
    """Create one group invite link."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO group_invites (id, group_id, token, created_by_user_id, expires_at, revoked_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                invite.id,
                invite.group_id,
                invite.token,
                invite.created_by_user_id,
                invite.expires_at.isoformat() if invite.expires_at else None,
                invite.revoked_at.isoformat() if invite.revoked_at else None,
                invite.created_at.isoformat(),
            ),
        )
    return invite


def _fetch_group_invite_by_token(token: str) -> GroupInvite | None:
    """Fetch one invite by public token."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM group_invites WHERE token = ?", (token,)).fetchone()
    return _row_to_group_invite(row)


def _revoke_group_invite(token: str, now: datetime) -> bool:
    """Revoke one active group invite."""
    with _connect() as conn:
        cursor = conn.execute("UPDATE group_invites SET revoked_at = ? WHERE token = ? AND revoked_at IS NULL", (now.isoformat(), token))
    return cursor.rowcount > 0


def _insert_message(message: ChatMessage) -> ChatMessage:
    """Store one chat message."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO messages (id, group_id, sender_id, sender_type, body, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (message.id, message.group_id, message.sender_id, message.sender_type.value, message.body, message.created_at.isoformat()),
        )
    return message


def _fetch_group_messages(group_id: str, limit: int = 50) -> list[ChatMessage]:
    """Fetch recent chat messages for one group."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE group_id = ? ORDER BY created_at DESC LIMIT ?",
            (group_id, limit),
        ).fetchall()
    return [message for row in reversed(rows) if (message := _row_to_message(row)) is not None]


def _insert_report(report: MemberReport) -> MemberReport:
    """Store one safety report."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO reports (id, reporter_user_id, target_type, target_id, reason, details, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (report.id, report.reporter_user_id, report.target_type.value, report.target_id, report.reason, report.details, report.created_at.isoformat()),
        )
    return report


def _insert_safety_block(block: SafetyBlock) -> SafetyBlock:
    """Block another user inside the app."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO safety_blocks (blocker_user_id, blocked_user_id, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(blocker_user_id, blocked_user_id) DO UPDATE SET
                created_at = excluded.created_at
            """,
            (block.blocker_user_id, block.blocked_user_id, block.created_at.isoformat()),
        )
    return block


def _delete_safety_block(blocker_user_id: str, blocked_user_id: str) -> bool:
    """Remove one safety block."""
    with _connect() as conn:
        cursor = conn.execute(
            "DELETE FROM safety_blocks WHERE blocker_user_id = ? AND blocked_user_id = ?",
            (blocker_user_id, blocked_user_id),
        )
    return cursor.rowcount > 0


def _is_blocked_between(user_id: str, other_user_id: str) -> bool:
    """Return whether either user has blocked the other."""
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM safety_blocks
            WHERE (blocker_user_id = ? AND blocked_user_id = ?)
               OR (blocker_user_id = ? AND blocked_user_id = ?)
            LIMIT 1
            """,
            (user_id, other_user_id, other_user_id, user_id),
        ).fetchone()
    return row is not None


def _insert_public_post(post: PublicPost) -> PublicPost:
    """Store one public feed post."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO posts (id, author_user_id, post_type, body, media_urls_json, tags_json, created_at, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (post.id, post.author_user_id, post.post_type.value, post.body, json.dumps(post.media_urls), json.dumps(post.tags), post.created_at.isoformat()),
        )
    return post


def _fetch_public_post(post_id: str) -> PublicPost | None:
    """Fetch one active public post."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM posts WHERE id = ? AND deleted_at IS NULL", (post_id,)).fetchone()
    return _row_to_public_post(row)


def _fetch_recent_public_posts(limit: int = 50) -> list[PublicPost]:
    """Fetch recent active posts for feed ranking."""
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM posts WHERE deleted_at IS NULL ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [post for row in rows if (post := _row_to_public_post(row)) is not None]


def _insert_post_like(post_id: str, user_id: str, now: datetime) -> bool:
    """Like a post once per user."""
    with _connect() as conn:
        cursor = conn.execute("INSERT OR IGNORE INTO post_likes (post_id, user_id, created_at) VALUES (?, ?, ?)", (post_id, user_id, now.isoformat()))
    return cursor.rowcount > 0


def _delete_post_like(post_id: str, user_id: str) -> bool:
    """Remove one post like."""
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM post_likes WHERE post_id = ? AND user_id = ?", (post_id, user_id))
    return cursor.rowcount > 0


def _count_post_likes(post_id: str) -> int:
    """Count likes for one post."""
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS total FROM post_likes WHERE post_id = ?", (post_id,)).fetchone()
    return int(row["total"])


def _insert_post_comment(comment: PostComment) -> PostComment:
    """Store one post comment."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO post_comments (id, post_id, author_user_id, body, created_at, deleted_at) VALUES (?, ?, ?, ?, ?, NULL)",
            (comment.id, comment.post_id, comment.author_user_id, comment.body, comment.created_at.isoformat()),
        )
    return comment


def _fetch_post_comments(post_id: str, limit: int = 50) -> list[PostComment]:
    """Fetch comments for one post."""
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM post_comments WHERE post_id = ? AND deleted_at IS NULL ORDER BY created_at DESC LIMIT ?", (post_id, limit)).fetchall()
    return [comment for row in reversed(rows) if (comment := _row_to_post_comment(row)) is not None]


def _fetch_post_comment(comment_id: str) -> PostComment | None:
    """Fetch one active post comment."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM post_comments WHERE id = ? AND deleted_at IS NULL", (comment_id,)).fetchone()
    return _row_to_post_comment(row)


def _count_post_comments(post_id: str) -> int:
    """Count comments for one post."""
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS total FROM post_comments WHERE post_id = ? AND deleted_at IS NULL", (post_id,)).fetchone()
    return int(row["total"])


def _insert_follow(follower_user_id: str, followed_user_id: str, now: datetime) -> bool:
    """Follow another user for updates."""
    with _connect() as conn:
        cursor = conn.execute("INSERT OR IGNORE INTO follows (follower_user_id, followed_user_id, created_at) VALUES (?, ?, ?)", (follower_user_id, followed_user_id, now.isoformat()))
    return cursor.rowcount > 0


def _delete_follow(follower_user_id: str, followed_user_id: str) -> bool:
    """Unfollow another user."""
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM follows WHERE follower_user_id = ? AND followed_user_id = ?", (follower_user_id, followed_user_id))
    return cursor.rowcount > 0


def _count_followers(user_id: str) -> int:
    """Count followers for one user."""
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS total FROM follows WHERE followed_user_id = ?", (user_id,)).fetchone()
    return int(row["total"])


def _fetch_followed_user_ids(user_id: str) -> set[str]:
    """Fetch user ids followed by one user."""
    with _connect() as conn:
        rows = conn.execute("SELECT followed_user_id FROM follows WHERE follower_user_id = ?", (user_id,)).fetchall()
    return {row["followed_user_id"] for row in rows}


def _insert_notification(notification: Notification) -> Notification:
    """Store one in-app notification."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO notifications (id, user_id, notification_type, title, body, related_id, read_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                notification.id,
                notification.user_id,
                notification.notification_type.value,
                notification.title,
                notification.body,
                notification.related_id,
                notification.read_at.isoformat() if notification.read_at else None,
                notification.created_at.isoformat(),
            ),
        )
    return notification


def _fetch_notifications(user_id: str, limit: int = 50) -> list[Notification]:
    """Fetch notifications for one user."""
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT ?", (user_id, limit)).fetchall()
    return [notification for row in rows if (notification := _row_to_notification(row)) is not None]


def _notification_exists(user_id: str, title: str, related_id: str) -> bool:
    """Return whether the same notification was already sent."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM notifications WHERE user_id = ? AND title = ? AND related_id = ? LIMIT 1",
            (user_id, title, related_id),
        ).fetchone()
    return row is not None


def _mark_notification_read(notification_id: str, user_id: str, now: datetime) -> bool:
    """Mark one notification read."""
    with _connect() as conn:
        cursor = conn.execute("UPDATE notifications SET read_at = ? WHERE id = ? AND user_id = ?", (now.isoformat(), notification_id, user_id))
    return cursor.rowcount > 0


def _insert_partner_request(request: PartnerRequest) -> PartnerRequest:
    """Store one partner request."""
    with _connect() as conn:
        try:
            conn.execute(
                """
                INSERT INTO partner_requests (id, requester_user_id, receiver_user_id, status, message, created_at, responded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (request.id, request.requester_user_id, request.receiver_user_id, request.status.value, request.message, request.created_at.isoformat(), None),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError("Partner request already exists") from error
    return request


def _fetch_partner_request(request_id: str) -> PartnerRequest | None:
    """Fetch one partner request."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM partner_requests WHERE id = ?", (request_id,)).fetchone()
    return _row_to_partner_request(row)


def _update_partner_request_status(request_id: str, receiver_user_id: str, status: PartnerRequestStatus, now: datetime) -> PartnerRequest | None:
    """Accept or decline a partner request."""
    with _connect() as conn:
        conn.execute(
            "UPDATE partner_requests SET status = ?, responded_at = ? WHERE id = ? AND receiver_user_id = ? AND status = ?",
            (status.value, now.isoformat(), request_id, receiver_user_id, PartnerRequestStatus.PENDING.value),
        )
        row = conn.execute("SELECT * FROM partner_requests WHERE id = ?", (request_id,)).fetchone()
    return _row_to_partner_request(row)


def _fetch_partner_requests_for_user(user_id: str, limit: int = 50) -> list[PartnerRequest]:
    """Fetch recent partner requests received by one user."""
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM partner_requests WHERE receiver_user_id = ? ORDER BY created_at DESC LIMIT ?", (user_id, limit)).fetchall()
    return [request for row in rows if (request := _row_to_partner_request(row)) is not None]


def _insert_profile_visit(visitor_user_id: str, visited_user_id: str, now: datetime) -> None:
    """Store one profile visit."""
    with _connect() as conn:
        conn.execute("INSERT INTO profile_visits (visitor_user_id, visited_user_id, visited_at) VALUES (?, ?, ?)", (visitor_user_id, visited_user_id, now.isoformat()))


def _count_recent_profile_visits(user_id: str, since: datetime) -> int:
    """Count recent profile visits for one user."""
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS total FROM profile_visits WHERE visited_user_id = ? AND visited_at >= ?", (user_id, since.isoformat())).fetchone()
    return int(row["total"])


# ============================================
# Public adapter API - stable reusable surface
# ============================================
def get_db_path() -> Path:
    """Return the database file path."""
    return DB_PATH


def init_db() -> None:
    """Public wrapper for initializing partner-match persistence."""
    _init_db()


def upsert_user_from_google(identity: GoogleIdentity, now: datetime) -> User:
    """Public wrapper for creating/updating a Google-backed user."""
    return _upsert_user_from_google(identity, now)


def fetch_user_by_id(user_id: str) -> User | None:
    """Public wrapper for fetching user by id."""
    return _fetch_user_by_id(user_id)


def touch_user_seen(user_id: str, now: datetime) -> User | None:
    """Public wrapper for refreshing last-seen time."""
    return _touch_user_seen(user_id, now)


def update_username(user_id: str, username: str) -> User:
    """Public wrapper for updating username."""
    return _update_username(user_id, username)


def soft_delete_user(user_id: str, now: datetime) -> bool:
    """Public wrapper for soft-deleting a user account."""
    return _soft_delete_user(user_id, now)


def insert_session(session: AuthSession) -> AuthSession:
    """Public wrapper for creating a session."""
    return _insert_session(session)


def fetch_session_by_token_id(token_id: str) -> AuthSession | None:
    """Public wrapper for fetching a session by JWT id."""
    return _fetch_session_by_token_id(token_id)


def upsert_profile(profile: PartnerProfile) -> PartnerProfile:
    """Public wrapper for saving a partner profile."""
    return _upsert_profile(profile)


def fetch_profile(user_id: str) -> PartnerProfile | None:
    """Public wrapper for fetching a partner profile."""
    return _fetch_profile(user_id)


def upsert_location(location: PartnerLocation) -> PartnerLocation:
    """Public wrapper for saving opt-in location state."""
    return _upsert_location(location)


def fetch_location(user_id: str) -> PartnerLocation | None:
    """Public wrapper for fetching location state."""
    return _fetch_location(user_id)


def fetch_location_candidates(exclude_user_id: str) -> list[tuple[User, PartnerProfile | None, PartnerLocation]]:
    """Public wrapper for fetching nearby-search candidates."""
    return _fetch_location_candidates(exclude_user_id)


def insert_group(group: PartnerGroup, admin_member: GroupMember) -> PartnerGroup:
    """Public wrapper for creating a partner group."""
    return _insert_group(group, admin_member)


def fetch_group(group_id: str) -> PartnerGroup | None:
    """Public wrapper for fetching a group."""
    return _fetch_group(group_id)


def fetch_user_groups(user_id: str) -> list[PartnerGroup]:
    """Public wrapper for fetching a user's groups."""
    return _fetch_user_groups(user_id)


def count_group_members(group_id: str) -> int:
    """Public wrapper for counting group members."""
    return _count_group_members(group_id)


def fetch_group_member(group_id: str, user_id: str) -> GroupMember | None:
    """Public wrapper for fetching a group member."""
    return _fetch_group_member(group_id, user_id)


def fetch_group_members(group_id: str) -> list[GroupMember]:
    """Public wrapper for fetching group members."""
    return _fetch_group_members(group_id)


def insert_group_member(member: GroupMember) -> GroupMember:
    """Public wrapper for adding a group member."""
    return _insert_group_member(member)


def delete_group_member(group_id: str, user_id: str) -> bool:
    """Public wrapper for removing a group member."""
    return _delete_group_member(group_id, user_id)


def insert_group_invite(invite: GroupInvite) -> GroupInvite:
    """Public wrapper for creating a group invite."""
    return _insert_group_invite(invite)


def fetch_group_invite_by_token(token: str) -> GroupInvite | None:
    """Public wrapper for fetching a group invite."""
    return _fetch_group_invite_by_token(token)


def revoke_group_invite(token: str, now: datetime) -> bool:
    """Public wrapper for revoking a group invite."""
    return _revoke_group_invite(token, now)


def insert_message(message: ChatMessage) -> ChatMessage:
    """Public wrapper for saving a chat message."""
    return _insert_message(message)


def fetch_group_messages(group_id: str, limit: int = 50) -> list[ChatMessage]:
    """Public wrapper for fetching group chat messages."""
    return _fetch_group_messages(group_id, limit)


def insert_report(report: MemberReport) -> MemberReport:
    """Public wrapper for saving a safety report."""
    return _insert_report(report)


def insert_safety_block(block: SafetyBlock) -> SafetyBlock:
    """Public wrapper for blocking a user."""
    return _insert_safety_block(block)


def delete_safety_block(blocker_user_id: str, blocked_user_id: str) -> bool:
    """Public wrapper for unblocking a user."""
    return _delete_safety_block(blocker_user_id, blocked_user_id)


def is_blocked_between(user_id: str, other_user_id: str) -> bool:
    """Public wrapper for checking whether either user blocked the other."""
    return _is_blocked_between(user_id, other_user_id)


def insert_public_post(post: PublicPost) -> PublicPost:
    """Public wrapper for saving a public post."""
    return _insert_public_post(post)


def fetch_public_post(post_id: str) -> PublicPost | None:
    """Public wrapper for fetching a public post."""
    return _fetch_public_post(post_id)


def fetch_recent_public_posts(limit: int = 50) -> list[PublicPost]:
    """Public wrapper for loading recent public posts."""
    return _fetch_recent_public_posts(limit)


def insert_post_like(post_id: str, user_id: str, now: datetime) -> bool:
    """Public wrapper for liking a post."""
    return _insert_post_like(post_id, user_id, now)


def delete_post_like(post_id: str, user_id: str) -> bool:
    """Public wrapper for unliking a post."""
    return _delete_post_like(post_id, user_id)


def count_post_likes(post_id: str) -> int:
    """Public wrapper for counting post likes."""
    return _count_post_likes(post_id)


def insert_post_comment(comment: PostComment) -> PostComment:
    """Public wrapper for saving a post comment."""
    return _insert_post_comment(comment)


def fetch_post_comments(post_id: str, limit: int = 50) -> list[PostComment]:
    """Public wrapper for fetching post comments."""
    return _fetch_post_comments(post_id, limit)


def fetch_post_comment(comment_id: str) -> PostComment | None:
    """Public wrapper for fetching one post comment."""
    return _fetch_post_comment(comment_id)


def count_post_comments(post_id: str) -> int:
    """Public wrapper for counting post comments."""
    return _count_post_comments(post_id)


def insert_follow(follower_user_id: str, followed_user_id: str, now: datetime) -> bool:
    """Public wrapper for following a user."""
    return _insert_follow(follower_user_id, followed_user_id, now)


def delete_follow(follower_user_id: str, followed_user_id: str) -> bool:
    """Public wrapper for unfollowing a user."""
    return _delete_follow(follower_user_id, followed_user_id)


def count_followers(user_id: str) -> int:
    """Public wrapper for counting followers."""
    return _count_followers(user_id)


def fetch_followed_user_ids(user_id: str) -> set[str]:
    """Public wrapper for fetching followed user ids."""
    return _fetch_followed_user_ids(user_id)


def insert_notification(notification: Notification) -> Notification:
    """Public wrapper for saving a notification."""
    return _insert_notification(notification)


def fetch_notifications(user_id: str, limit: int = 50) -> list[Notification]:
    """Public wrapper for fetching notifications."""
    return _fetch_notifications(user_id, limit)


def notification_exists(user_id: str, title: str, related_id: str) -> bool:
    """Public wrapper for notification de-duplication."""
    return _notification_exists(user_id, title, related_id)


def mark_notification_read(notification_id: str, user_id: str, now: datetime) -> bool:
    """Public wrapper for marking notification read."""
    return _mark_notification_read(notification_id, user_id, now)


def insert_partner_request(request: PartnerRequest) -> PartnerRequest:
    """Public wrapper for saving a partner request."""
    return _insert_partner_request(request)


def fetch_partner_request(request_id: str) -> PartnerRequest | None:
    """Public wrapper for fetching a partner request."""
    return _fetch_partner_request(request_id)


def update_partner_request_status(request_id: str, receiver_user_id: str, status: PartnerRequestStatus, now: datetime) -> PartnerRequest | None:
    """Public wrapper for responding to a partner request."""
    return _update_partner_request_status(request_id, receiver_user_id, status, now)


def fetch_partner_requests_for_user(user_id: str, limit: int = 50) -> list[PartnerRequest]:
    """Public wrapper for fetching partner requests."""
    return _fetch_partner_requests_for_user(user_id, limit)


def insert_profile_visit(visitor_user_id: str, visited_user_id: str, now: datetime) -> None:
    """Public wrapper for saving a profile visit."""
    _insert_profile_visit(visitor_user_id, visited_user_id, now)


def count_recent_profile_visits(user_id: str, since: datetime) -> int:
    """Public wrapper for counting recent profile visits."""
    return _count_recent_profile_visits(user_id, since)
