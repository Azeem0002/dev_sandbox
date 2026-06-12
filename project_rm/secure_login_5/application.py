"""Application/orchestration layer for secure_login_5."""

from datetime import datetime, timedelta, timezone
import uuid

try:
    from .database_adapter import fetch_session_by_token_id, fetch_user_by_email, fetch_user_by_id, insert_session, insert_user, revoke_session
    from .models import AuthResult, AuthSession, LoginUserDTO, RegisterUserDTO, User, UserDTO
    from .security_adapter import create_access_token, create_token_id, decode_access_token, get_access_token_seconds, hash_password, verify_password
except ImportError:
    from database_adapter import fetch_session_by_token_id, fetch_user_by_email, fetch_user_by_id, insert_session, insert_user, revoke_session
    from models import AuthResult, AuthSession, LoginUserDTO, RegisterUserDTO, User, UserDTO
    from security_adapter import create_access_token, create_token_id, decode_access_token, get_access_token_seconds, hash_password, verify_password


def _utc_now() -> datetime:
    """Return timezone-aware UTC now for auth decisions."""
    return datetime.now(timezone.utc)


def _build_user(data: RegisterUserDTO) -> User:
    """Build a new internal user model from registration input."""
    return User(id=str(uuid.uuid4()), email=data.email, password_hash=hash_password(data.password), created_at=_utc_now())


def _build_user_dto(user: User) -> UserDTO:
    """Map internal user to public-safe DTO."""
    return UserDTO(id=user.id, email=user.email, created_at=user.created_at)


def _build_auth_session(user_id: str, token_id: str, expires_in_seconds: int) -> AuthSession:
    """Build a server-side session record for one JWT."""
    return AuthSession(id=str(uuid.uuid4()), user_id=user_id, token_id=token_id, expires_at=_utc_now() + timedelta(seconds=expires_in_seconds))


def _build_auth_result(user: User) -> AuthResult:
    """Create a session and token for an authenticated user."""
    token_id = create_token_id()
    expires_in_seconds = get_access_token_seconds()
    session = insert_session(_build_auth_session(user.id, token_id, expires_in_seconds))
    access_token = create_access_token(user_id=user.id, token_id=token_id, expires_in_seconds=expires_in_seconds)
    return AuthResult(user=user, session=session, access_token=access_token, expires_in_seconds=expires_in_seconds)


# ============================================
# Application / Orchestration - Public use cases
# Start reading internals from here.
# ============================================
def register_user(data: RegisterUserDTO) -> AuthResult:
    """Create a new user, session, and access token."""
    if fetch_user_by_email(data.email) is not None:
        raise ValueError("Email is already registered")
    return _build_auth_result(insert_user(_build_user(data)))


def login_user(data: LoginUserDTO) -> AuthResult:
    """Authenticate user credentials and create a new session/token."""
    user = fetch_user_by_email(data.email)
    if user is None or not verify_password(data.password, user.password_hash):
        raise ValueError("Invalid email or password")
    return _build_auth_result(user)


def get_current_user(access_token: str) -> UserDTO:
    """Verify token, check session state, and return the current user."""
    payload = decode_access_token(access_token)
    token_id = str(payload.get("jti") or "")
    user_id = str(payload.get("sub") or "")
    session = fetch_session_by_token_id(token_id)
    if session is None or session.revoked_at is not None or session.expires_at <= _utc_now():
        raise ValueError("Session is not active")
    user = fetch_user_by_id(user_id)
    if user is None:
        raise ValueError("User not found")
    return _build_user_dto(user)


def logout_user(access_token: str) -> bool:
    """Revoke the current JWT session."""
    payload = decode_access_token(access_token)
    token_id = str(payload.get("jti") or "")
    return revoke_session(token_id)
