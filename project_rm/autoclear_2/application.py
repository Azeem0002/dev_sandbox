"""Application/orchestration layer for autoclear.

Boundary code calls this module with already-parsed inputs.
This layer chooses the right backend and coordinates process/service adapters.
"""

import os

try:
    from .autoclear import run_autoclear
    from .lifecycle_models import AutoclearStatus
    from .lifecycle_models import AutoclearConfig
    from .platform_adapter import detect_platform
    from .validation import format_duration_seconds, parse_interval
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
    from autoclear import run_autoclear
    from lifecycle_models import AutoclearStatus
    from lifecycle_models import AutoclearConfig
    from platform_adapter import detect_platform
    from validation import format_duration_seconds, parse_interval
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


def _format_process_start_message(action: str, pid: int, interval_secs: int, target_tty: str | None = None) -> str:
    """Build the user-facing process backend startup message."""
    interval_label = format_duration_seconds(interval_secs)
    target_text = f"; target terminal {target_tty}" if target_tty else ""
    return f"Autoclear {action} in background (PID {pid}) with interval {interval_label}{target_text}; first clear starts immediately, then every {interval_label}"


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
    status = get_status_from_process()
    return _format_process_start_message("started", pid, interval_secs, status.target_tty)


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
    interval_secs = parse_interval(interval)
    platform = detect_platform()

    stop_autoclear()

    if platform == "linux" and is_service_installed(system=False):
        return start_service(interval_secs=interval_secs, system=False)

    pid = spawn_detached_process(interval_secs=interval_secs)
    status = get_status_from_process()
    return _format_process_start_message("restarted", pid, interval_secs, status.target_tty)


def watch_autoclear(interval: str) -> None:
    """
    Clear the current terminal from a foreground loop.

    Flow:
        watch -> watch_autoclear
        watch_autoclear
            -> parse_interval
            -> run_autoclear
    """
    interval_secs = parse_interval(interval)
    os.environ["AUTOCLEAR_SILENT"] = "1"
    run_autoclear(AutoclearConfig(interval=interval_secs))
