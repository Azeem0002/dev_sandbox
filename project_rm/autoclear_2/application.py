"""Application/orchestration layer for autoclear.

Boundary code calls this module with already-parsed inputs.
This layer chooses the right backend and coordinates process/service adapters.
"""

try:
    from .lifecycle_models import AutoclearStatus
    from .platform_adapter import detect_platform
    from .validation import parse_interval
    from .process_adapter import (
        get_status_from_process,
        spawn_detached_process,
        stop_process,
    )
    from .service_adapter import (
        get_status_from_systemd,
        install_service,
        is_service_installed,
        start_service,
        stop_service,
    )
except ImportError:
    from lifecycle_models import AutoclearStatus
    from platform_adapter import detect_platform
    from validation import parse_interval
    from process_adapter import (
        get_status_from_process,
        spawn_detached_process,
        stop_process,
    )
    from service_adapter import (
        get_status_from_systemd,
        install_service,
        is_service_installed,
        start_service,
        stop_service,
    )


def install_autoclear_service(interval: str = "1h", system: bool = False) -> tuple[str, list[str]]:
    """
    Install the native background backend for this platform after parsing the human interval input.

    Flow:
        install-service -> install_autoclear_service
        install_autoclear_service
            -> parse_interval
            -> detect_platform
            -> install_service
    """
    # Application chooses the native backend that matches the current platform.
    interval_secs = parse_interval(interval)
    platform = detect_platform()

    if platform == "linux":
        return install_service(interval_secs=interval_secs, system=system)

    if platform == "windows":
        return ("Windows uses the process backend for autoclear", ["Use `start` to launch autoclear"])

    if platform == "mac":
        return ("macOS not yet supported for service install", ["Use `start` to launch autoclear"])

    raise RuntimeError(f"Unsupported platform: {platform}")


# ============================================
# Application / Orchestration - Public use cases
# Start reading internals from here.
# ============================================
def get_autoclear_status() -> AutoclearStatus:
    """
    Return status from the preferred backend: systemd timer on Linux, detached worker elsewhere.

    Flow:
        status -> get_autoclear_status
        get_autoclear_status
            -> detect_platform
            -> get_status_from_systemd | get_status_from_process
    """
    # Linux prefers the native timer/service backend when it is installed.
    platform = detect_platform()
    if platform == "linux" and is_service_installed(system=False):
        return get_status_from_systemd(system=False)

    return get_status_from_process()


def start_autoclear(interval: str) -> str:
    """
    Start autoclear using the backend that makes sense for the current platform.

    Flow:
        start -> start_autoclear
        start_autoclear
            -> parse_interval
            -> detect_platform
            -> start_service | spawn_detached_process
    """
    # One use-case, different infrastructure by platform.
    interval_secs = parse_interval(interval)
    platform = detect_platform()

    if platform == "linux" and is_service_installed(system=False):
        return start_service(interval_secs=interval_secs, system=False)

    pid = spawn_detached_process(interval_secs=interval_secs)
    return f"Autoclear started in background (PID {pid})"


def stop_autoclear() -> str:
    """
    Stop autoclear through the same backend-selection rules used for start/status.

    Flow:
        stop -> stop_autoclear
        stop_autoclear
            -> detect_platform
            -> stop_service | stop_process
    """
    # Stop follows the same backend decision as start/status.
    platform = detect_platform()

    if platform == "linux" and is_service_installed(system=False):
        return stop_service(system=False)

    # process for windows
    stopped = stop_process()
    if stopped:
        return "Autoclear process backend stopped"
    return "Autoclear already stopped"


def restart_autoclear(interval: str) -> str:
    """
    Stop the current autoclear backend and start it again with the requested interval.

    Flow:
        restart -> restart_autoclear
        restart_autoclear
            -> stop_autoclear
            -> start_autoclear
    """
    stop_autoclear()
    return start_autoclear(interval)
