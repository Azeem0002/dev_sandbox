"""Hosting adapter for adbot_9.

This adapter keeps deployment facts in one predictable place. It does not
start the server; boundary tools, docs, or deployment platforms use this data.
"""

from dataclasses import dataclass


APP_NAME = "adbot_9"
APP_KIND = "fastapi_api"
ENTRYPOINT = "adbot_9.api:app"
APP_MODULE = ENTRYPOINT
HEALTH_PATH = "/health"
NEEDS_ALWAYS_ON = False
HOSTING_NOTE = "API can run on a simple web host; use a worker only after scheduled campaign monitoring is added."


@dataclass(frozen=True)
class HostingProfile:
    """Small DTO that describes how this project should be hosted."""

    app_name: str
    app_kind: str
    entrypoint: str
    health_path: str
    needs_always_on: bool
    note: str


# ============================================
# Hosting adapter - reusable mental map
# ============================================
# A hosting adapter belongs at the infrastructure edge: it describes how to run
# the app on a host, but it does not decide business rules or start hidden work.


# ============================================
# Shared private skeleton - start reading here
# ============================================
def _get_hosting_profile() -> HostingProfile:
    """Build the deploy-time profile for this project."""
    return HostingProfile(
        app_name=APP_NAME,
        app_kind=APP_KIND,
        entrypoint=ENTRYPOINT,
        health_path=HEALTH_PATH,
        needs_always_on=NEEDS_ALWAYS_ON,
        note=HOSTING_NOTE,
    )


def _build_host_command(host: str = "127.0.0.1", port: int = 8000) -> list[str]:
    """Return the command a host/process manager should run."""
    return ["uvicorn", APP_MODULE, "--host", host, "--port", str(port)]


def _build_healthcheck_url(base_url: str) -> str:
    """Join a deployed base URL with this app's health endpoint."""
    return f"{base_url.rstrip('/')}{HEALTH_PATH}"


# ============================================
# Project-specific aliases
# ============================================
def _build_uvicorn_command(host: str = "127.0.0.1", port: int = 8000) -> list[str]:
    """Return the standard Uvicorn command without executing it."""
    return _build_host_command(host=host, port=port)


# ============================================
# Public adapter API
# Responsibility-order adapters are grouped by the job they do, not by install/start/stop lifecycle.
# Read them as: prepare inputs -> call the outside system -> map results back to app-safe data.
# ============================================
def get_hosting_profile() -> HostingProfile:
    """Return hosting metadata for docs, deployment scripts, or checks."""
    return _get_hosting_profile()


def build_host_command(host: str = "127.0.0.1", port: int = 8000) -> list[str]:
    """Return the command a host/process manager should run."""
    return _build_host_command(host=host, port=port)


def build_healthcheck_url(base_url: str) -> str:
    """Return the healthcheck URL for a deployed app base URL."""
    return _build_healthcheck_url(base_url)


def build_uvicorn_command(host: str = "127.0.0.1", port: int = 8000) -> list[str]:
    """Return the command a platform can use to run this FastAPI app."""
    return _build_uvicorn_command(host=host, port=port)
