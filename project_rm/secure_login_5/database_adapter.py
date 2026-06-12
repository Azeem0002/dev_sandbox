#!/usr/bin/env python3
"""SQLite database adapter for secure_login_5."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

try:
    from .models import AuthSession, User
    from .runtime_support import get_platform_dirs
except ImportError:
    from models import AuthSession, User
    from runtime_support import get_platform_dirs


# ============================================
# Database adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================
dirs = get_platform_dirs()


def _get_db_path() -> Path:
    """Return the database file path."""
    # One database file can still support many individual users through rows.
    # Do not create one SQLite file per user unless there is a strong isolation requirement.
    return Path(dirs.user_data_dir) / "secure_login.db"


DB_PATH = _get_db_path()


def _utc_now_iso() -> str:
    """Return current UTC time serialized for SQLite."""
    return datetime.now(timezone.utc).isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse stored ISO datetime text into datetime."""
    return datetime.fromisoformat(value) if value else None


def _init_db() -> None:
    """Initialize auth database schema and indexes."""
    # Init is the explicit setup step, so parent-dir creation belongs here.
    DB_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
        # Sessions make logout possible. JWT-only auth cannot revoke a token until it expires.
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
        logger.debug("Secure login database initialized")


def _row_to_user(row: sqlite3.Row | None) -> User | None:
    """Map one SQLite user row into an internal user model."""
    if row is None:
        return None
    return User(id=row["id"], email=row["email"], password_hash=row["password_hash"], created_at=datetime.fromisoformat(row["created_at"]))


def _row_to_session(row: sqlite3.Row | None) -> AuthSession | None:
    """Map one SQLite session row into an internal session model."""
    if row is None:
        return None
    return AuthSession(id=row["id"], user_id=row["user_id"], token_id=row["token_id"], expires_at=datetime.fromisoformat(row["expires_at"]), revoked_at=_parse_datetime(row["revoked_at"]))


@retry(retry=retry_if_exception_type(sqlite3.OperationalError), stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5), reraise=True)
def _insert_user(user: User) -> User:
    """Insert one user row."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO users (id, email, password_hash, created_at) VALUES (?, ?, ?, ?)", (user.id, user.email, user.password_hash, user.created_at.isoformat()))
    return user


def _fetch_user_by_email(email: str) -> User | None:
    """Fetch one user by normalized email."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return _row_to_user(row)


def _fetch_user_by_id(user_id: str) -> User | None:
    """Fetch one user by id."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _row_to_user(row)


def _insert_session(session: AuthSession) -> AuthSession:
    """Insert one auth session."""
    with sqlite3.connect(DB_PATH) as conn:
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
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM sessions WHERE token_id = ?", (token_id,)).fetchone()
    return _row_to_session(row)


def _revoke_session(token_id: str) -> bool:
    """Mark one session revoked."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("UPDATE sessions SET revoked_at = ? WHERE token_id = ? AND revoked_at IS NULL", (_utc_now_iso(), token_id))
    return cursor.rowcount > 0


# ============================================
# Public adapter API - stable reusable surface
# ============================================
def get_db_path() -> Path:
    """Return the database file path."""
    return DB_PATH


def init_db() -> None:
    """Public wrapper for initializing auth persistence."""
    _init_db()


def insert_user(user: User) -> User:
    """Public wrapper for creating a user."""
    return _insert_user(user)


def fetch_user_by_email(email: str) -> User | None:
    """Public wrapper for fetching user by email."""
    return _fetch_user_by_email(email)


def fetch_user_by_id(user_id: str) -> User | None:
    """Public wrapper for fetching user by id."""
    return _fetch_user_by_id(user_id)


def insert_session(session: AuthSession) -> AuthSession:
    """Public wrapper for creating a session."""
    return _insert_session(session)


def fetch_session_by_token_id(token_id: str) -> AuthSession | None:
    """Public wrapper for fetching a session by JWT id."""
    return _fetch_session_by_token_id(token_id)


def revoke_session(token_id: str) -> bool:
    """Public wrapper for revoking a session."""
    return _revoke_session(token_id)
