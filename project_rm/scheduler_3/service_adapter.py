"""Native service/task facade for scheduler.

This module chooses the native service backend for the current platform.
Linux details live in systemd_adapter.py. Windows details live in
task_scheduler_adapter.py.
"""

try:
    from .platform_adapter import detect_platform
    from .systemd_adapter import (
        install_systemd_service,
        is_systemd_service_installed,
        start_systemd_service,
        stop_systemd_service,
    )
    from .task_scheduler_adapter import install_task_scheduler_service
except ImportError:
    from platform_adapter import detect_platform
    from systemd_adapter import (
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
    """Install the native OS service/task definition for the scheduler app."""
    del interval_secs

    platform = detect_platform()

    if platform == "linux":
        return install_systemd_service(system=system)

    if platform == "windows":
        return install_task_scheduler_service()

    if platform == "mac":
        return (
            "macOS not yet supported",
            ["Use launchd manually or run with --foreground"],
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
    del interval_secs

    platform = detect_platform()
    if platform == "linux":
        return start_systemd_service(system=system)
    if platform == "windows":
        raise RuntimeError("Windows scheduled task start is not exposed through service_adapter")
    raise RuntimeError(f"Unsupported platform: {platform}")


def stop_service(*, system: bool = False) -> str:
    """Stop the installed native service backend."""
    platform = detect_platform()
    if platform == "linux":
        return stop_systemd_service(system=system)
    if platform == "windows":
        raise RuntimeError("Windows scheduled task stop is not exposed through service_adapter")
    raise RuntimeError(f"Unsupported platform: {platform}")


install_scheduler_service = install_service
service_is_installed = is_service_installed
