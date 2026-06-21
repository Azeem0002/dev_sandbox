"""Native service/task facade for autoclear.

This module chooses the native service backend for the current platform.
Linux details live in systemd_adapter.py. Windows details live in
task_scheduler_adapter.py.
"""

try:
    from .lifecycle_models import AutoclearStatus
    from .platform_adapter import detect_platform
    from .systemd_adapter import (
        get_status_from_systemd,
        install_systemd_service,
        is_systemd_service_installed,
        start_systemd_service,
        stop_systemd_service,
    )
    from .task_scheduler_adapter import install_task_scheduler_service
except ImportError:
    from lifecycle_models import AutoclearStatus
    from platform_adapter import detect_platform
    from systemd_adapter import (
        get_status_from_systemd,
        install_systemd_service,
        is_systemd_service_installed,
        start_systemd_service,
        stop_systemd_service,
    )
    from task_scheduler_adapter import install_task_scheduler_service


# ============================================
# Service adapter - reusable mental map
# ============================================
# Service adapter is the cross-platform facade. It chooses the current OS
# backend, then delegates to systemd_adapter.py on Linux or
# task_scheduler_adapter.py on Windows. Keep OS-specific command text out of
# this module so the mental model stays: choose backend -> delegate -> return.

# ============================================
# Public adapter API - stable reusable surface
# ============================================
def install_service(*, interval_secs: int | None = None, system: bool = False) -> tuple[str, list[str]]:
    """Install the native OS service/task definition for autoclear."""
    if interval_secs is None:
        raise ValueError("interval_secs is required to install autoclear service")

    platform = detect_platform()

    if platform == "linux":
        return install_systemd_service(interval_secs=interval_secs, system=system)

    if platform == "windows":
        return install_task_scheduler_service(interval_secs=interval_secs)

    if platform == "mac":
        return (
            "macOS not yet supported",
            ["Use launchd manually or run `autoclear start`."],
        )

    raise RuntimeError(f"Unsupported platform: {platform}")


def is_service_installed(*, system: bool = False) -> bool:
    """Report whether the native service definition is installed."""
    platform = detect_platform()
    if platform == "linux":
        return is_systemd_service_installed(system=system)
    return False


def start_service(*, interval_secs: int | None = None, system: bool = False) -> str:
    """Start the installed native service backend."""
    platform = detect_platform()
    if platform == "linux":
        return start_systemd_service(interval_secs=interval_secs, system=system)
    if platform == "windows":
        raise RuntimeError("Windows task start is not exposed through service_adapter")
    raise RuntimeError(f"Unsupported platform: {platform}")


def stop_service(*, system: bool = False) -> str:
    """Stop the installed native service backend."""
    platform = detect_platform()
    if platform == "linux":
        return stop_systemd_service(system=system)
    if platform == "windows":
        raise RuntimeError("Windows task stop is not exposed through service_adapter")
    raise RuntimeError(f"Unsupported platform: {platform}")


def get_service_status_from_systemd(*, system: bool) -> AutoclearStatus:
    """Return Linux systemd status through the service facade."""
    return get_status_from_systemd(system=system)
