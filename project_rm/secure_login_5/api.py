#!/usr/bin/env python3
"""FastAPI boundary for secure_login_5."""

from fastapi import Depends, FastAPI, Header, HTTPException, status

try:
    from .application import get_current_user, login_user, login_with_google, logout_user, register_user
    from .database_adapter import init_db
    from .models import GoogleLoginDTO, LoginUserDTO, RegisterUserDTO, TokenDTO, UserDTO
    from .runtime_adapter import setup_environment, setup_logger
    from .validation import build_login_user_request, build_register_user_request
except ImportError:
    from application import get_current_user, login_user, login_with_google, logout_user, register_user
    from database_adapter import init_db
    from models import GoogleLoginDTO, LoginUserDTO, RegisterUserDTO, TokenDTO, UserDTO
    from runtime_adapter import setup_environment, setup_logger
    from validation import build_login_user_request, build_register_user_request


app = FastAPI(title="secure_login_5", version="0.1.0")


# ============================================
# API boundary - thin wrapper around orchestration
# ============================================
@app.on_event("startup")
def startup() -> None:
    """Prepare runtime logging and database before serving requests."""
    log_file = setup_environment()
    setup_logger(log_file)
    init_db()


def _extract_bearer_token(authorization: str | None = Header(default=None)) -> str:
    """Extract a bearer token from the Authorization header."""
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.casefold() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Use Bearer token")
    return token


@app.get("/health")
def health() -> dict[str, str]:
    """Return a small liveness response."""
    return {"status": "ok"}


@app.post("/register", response_model=TokenDTO)
def register(payload: RegisterUserDTO) -> TokenDTO:
    """Register a user and return a JWT access token."""
    try:
        result = register_user(build_register_user_request(payload))
        return TokenDTO(access_token=result.access_token, expires_in_seconds=result.expires_in_seconds)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@app.post("/login", response_model=TokenDTO)
def login(payload: LoginUserDTO) -> TokenDTO:
    """Login a user and return a JWT access token."""
    try:
        result = login_user(build_login_user_request(payload))
        return TokenDTO(access_token=result.access_token, expires_in_seconds=result.expires_in_seconds)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error


@app.post("/auth/google", response_model=TokenDTO)
def google_login(payload: GoogleLoginDTO) -> TokenDTO:
    """Login with Google and return a JWT access token."""
    try:
        result = login_with_google(payload)
        return TokenDTO(access_token=result.access_token, expires_in_seconds=result.expires_in_seconds)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error


@app.get("/me", response_model=UserDTO)
def me(access_token: str = Depends(_extract_bearer_token)) -> UserDTO:
    """Return the current user from the bearer token."""
    try:
        return get_current_user(access_token)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error


@app.post("/logout")
def logout(access_token: str = Depends(_extract_bearer_token)) -> dict[str, bool]:
    """Revoke the current session token."""
    try:
        return {"revoked": logout_user(access_token)}
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
