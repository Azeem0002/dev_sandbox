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
    from .task_scheduler_adapter import get_status_from_task_scheduler
    from .task_scheduler_adapter import is_task_scheduler_service_installed
    from .task_scheduler_adapter import start_task_scheduler_service
    from .task_scheduler_adapter import stop_task_scheduler_service
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
    from task_scheduler_adapter import (
        get_status_from_task_scheduler,
        is_task_scheduler_service_installed,
        install_task_scheduler_service,
        start_task_scheduler_service,
        stop_task_scheduler_service
    )

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
# Public functions use lifecycle workflow order: check installed state, install/update,
# start, stop, then read status. This matches how an operator thinks about a service.
def is_service_installed(*, system: bool = False) -> bool:
    """Report whether the native service/task definition is installed."""
    platform = detect_platform()
    if platform == "linux":
        return is_systemd_service_installed(system=system)
    
    if platform == "windows":
        return is_task_scheduler_service_installed()
    
    if platform == "mac":
        return False
    
    return False


def install_service(*, interval_secs: int | None = None, system: bool = False) -> tuple[str, list[str]]:
    """Install or update the native OS service/task definition for autoclear."""
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



def start_service(*, interval_secs: int | None = None, system: bool = False) -> str:
    """Start the installed native service backend."""
    platform = detect_platform()
    if platform == "linux":
        return start_systemd_service(interval_secs=interval_secs, system=system)
    if platform == "windows":
        return start_task_scheduler_service()
    raise RuntimeError(f"Unsupported platform: {platform}")


def stop_service(*, system: bool = False) -> str:
    """Stop the installed native service backend."""
    platform = detect_platform()
    if platform == "linux":
        return stop_systemd_service(system=system)
    if platform == "windows":
        return stop_task_scheduler_service()
    raise RuntimeError(f"Unsupported platform: {platform}")


def get_service_status(*, system: bool = False) -> AutoclearStatus:
    """Return status from the native service/task backend for the current platform."""
    # The facade chooses the platform only. Each platform adapter owns its own
    # status parsing and turns native OS details into this project's status model.
    platform = detect_platform()
    if platform == "linux":
        return get_status_from_systemd(system=system)
    if platform == "windows":
        return get_status_from_task_scheduler()
    raise RuntimeError(f"Unsupported platform: {platform}")
