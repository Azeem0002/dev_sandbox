"""Hosting adapter for scheduler_3.

This adapter describes how the scheduler should live on a server. The scheduler
is not a normal request/response API; it is an always-on worker/daemon.
"""

from dataclasses import dataclass
import sys


APP_NAME = "scheduler_3"
APP_KIND = "always_on_worker"
ENTRYPOINT = "scheduler_3/scheduler.py"
HEALTH_PATH = None
NEEDS_ALWAYS_ON = True
HOSTING_NOTE = "Micro-SaaS scheduler should run on a VPS/server as a long-running worker, ideally via systemd."


@dataclass(frozen=True)
class HostingProfile:
    """Small DTO that describes how this project should be hosted."""

    app_name: str
    app_kind: str
    entrypoint: str
    health_path: str | None
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


def _build_host_command() -> list[str]:
    """Return the foreground worker command a server process manager should run."""
    return [sys.executable, ENTRYPOINT, "start", "--foreground"]


def _build_healthcheck_url(base_url: str) -> str | None:
    """Return `None` because scheduler is a worker, not an HTTP app."""
    del base_url
    return None


# ============================================
# Project-specific aliases
# ============================================
def _build_worker_command() -> list[str]:
    """Return the foreground worker command a server process manager should run."""
    return _build_host_command()


# ============================================
# Public adapter API
# ============================================
def get_hosting_profile() -> HostingProfile:
    """Return hosting metadata for docs, deployment scripts, or checks."""
    return _get_hosting_profile()


def build_host_command() -> list[str]:
    """Return the command a host/process manager should run."""
    return _build_host_command()


def build_healthcheck_url(base_url: str) -> str | None:
    """Return the healthcheck URL when the project exposes one."""
    return _build_healthcheck_url(base_url)


def build_worker_command() -> list[str]:
    """Return the command a server supervisor can use to run this scheduler."""
    return _build_worker_command()
