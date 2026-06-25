"""Application/orchestration layer for autoclear.

Boundary code calls this module with already-parsed inputs.
This layer chooses the right backend and coordinates process/service adapters.
"""

try:
    from .lifecycle_models import AutoclearStatus
    from .platform_adapter import detect_platform
    from .validation import format_duration_seconds, parse_interval
    from .process_adapter import (
        get_status_from_process,
        spawn_detached_process,
        stop_process,
    )
    from .service_adapter import (
        get_service_status,
        install_service,
        is_service_installed,
        start_service,
        stop_service,
    )
except ImportError:
    from lifecycle_models import AutoclearStatus
    from platform_adapter import detect_platform
    from validation import format_duration_seconds, parse_interval
    from process_adapter import (
        get_status_from_process,
        spawn_detached_process,
        stop_process,
    )
    from service_adapter import (
        get_service_status,
        install_service,
        is_service_installed,
        start_service,
        stop_service,
    )


def install_autoclear_service(interval: str = "1h", system: bool = False) -> tuple[str, list[str]]:
    """
    Install or update the native background backend after parsing the human interval input.

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

    if platform in {"linux", "windows"}:
        return install_service(interval_secs=interval_secs, system=system)

    if platform == "mac":
        return ("macOS not yet supported for service install", ["Use `start` to launch autoclear"])

    raise RuntimeError(f"Unsupported platform: {platform}")


def _format_process_start_message(action: str, pid: int, interval_secs: int, target_tty: str | None = None) -> str:
    """Build the user-facing process backend startup message."""
    interval_label = format_duration_seconds(interval_secs)
    target_text = f"; target terminal {target_tty}" if target_tty else ""
    return f"Autoclear {action} in background (PID: {pid}) with interval {interval_label}{target_text}; first clear starts immediately, then every {interval_label}"


# ============================================
# Application / Orchestration - Public use cases
# Start reading internals from here.
# ============================================
def get_autoclear_status(*, system: bool = False) -> AutoclearStatus:
    """
    Return status from the preferred backend: native service/task when installed, detached worker elsewhere.

    Flow:
        status -> get_autoclear_status
        get_autoclear_status
            -> detect_platform
            -> get_service_status | get_status_from_process
    """
    platform = detect_platform()
    if system and platform == "linux":
        return get_service_status(system=system)

    if platform in {"linux", "windows"} and is_service_installed(system=system):
        return get_service_status(system=system)

    return get_status_from_process()


def start_autoclear(interval: str, *, system: bool = False) -> str:
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

    if system and platform == "linux":
        return start_service(interval_secs=interval_secs, system=system)

    if platform in {"linux", "windows"} and is_service_installed(system=system):
        return start_service(interval_secs=interval_secs, system=system)

    pid = spawn_detached_process(interval_secs=interval_secs)
    status = get_status_from_process()
    return _format_process_start_message("started", pid, interval_secs, status.target_tty)


def stop_autoclear(*, system: bool = False) -> str:
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

    if system and platform == "linux":
        return stop_service(system=system)

    if platform in {"linux", "windows"} and is_service_installed(system=system):
        return stop_service(system=system)

    # process for windows
    stopped = stop_process()
    if stopped:
        return "Autoclear process backend stopped"
    return "Autoclear already stopped"


def restart_autoclear(interval: str, *, system: bool = False) -> str:
    """
    Stop the current autoclear backend and start it again with the requested interval.

    Flow:
        restart -> restart_autoclear
        restart_autoclear
            -> stop_autoclear
            -> start_autoclear
    """
    interval_secs = parse_interval(interval)
    platform = detect_platform()

    stop_autoclear(system=system)

    if system and platform == "linux":
        return start_service(interval_secs=interval_secs, system=system)

    if platform in {"linux", "windows"} and is_service_installed(system=system):
        return start_service(interval_secs=interval_secs, system=system)

    pid = spawn_detached_process(interval_secs=interval_secs)
    status = get_status_from_process()
    return _format_process_start_message("restarted", pid, interval_secs, status.target_tty)
