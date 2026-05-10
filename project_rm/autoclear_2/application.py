"""Application/orchestration layer for autoclear.

Boundary code calls this module with already-parsed inputs.
This layer chooses the right backend and coordinates process/service adapters.
"""

from pathlib import Path

import pytimeparse

try:
    from .lifecycle_models import AutoclearStatus
    from .platform_adapter import _detect_platform
    from .process_adapter import (
        get_active_process_pid,
        get_pid_file_path,
        get_process,
        read_process_interval_seconds,
        spawn_detached_process,
        stop_process,
    )
    from .service_adapter import (
        _status_from_systemd,
        install_service,
        start_service,
        stop_service,
    )
except ImportError:
    from lifecycle_models import AutoclearStatus
    from platform_adapter import _detect_platform
    from process_adapter import (
        get_active_process_pid,
        get_pid_file_path,
        get_process,
        read_process_interval_seconds,
        spawn_detached_process,
        stop_process,
    )
    from service_adapter import (
        _status_from_systemd,
        install_service,
        start_service,
        stop_service,
    )


def _parse_interval(value: str) -> int:
    """Convert flexible user input like `10s`, `5m`, or `3600` into a bounded integer interval in seconds."""
    if value.isdigit():
        seconds = int(value)  # already plain seconds
    else:
        parsed = pytimeparse.parse(value)
        if parsed is None:
            raise ValueError(f"Invalid time format: {value}")
        seconds = int(parsed)

    if seconds <= 0:
        raise ValueError("Interval must be > 0")
    if seconds > 172800:
        raise ValueError("Interval too large. (max 2 days)")
    return seconds


def _build_process_stopped_status(detail: str, pid_file: Path) -> AutoclearStatus:
    """Build the public status model for the 'autoclear process backend is not running' case."""
    return AutoclearStatus(
        backend="process",
        is_running=False,
        pid=None,
        interval_seconds=None,
        last_trigger=None,
        detail=detail,
        pid_file=pid_file,
    )


def _build_process_running_status(pid: int, pid_file: Path) -> AutoclearStatus:
    """Build the public status model for the 'autoclear process backend is alive' case."""
    process = get_process(pid)
    # Process adapter knows how the worker encodes its interval in CLI args.
    interval = read_process_interval_seconds(process) if process is not None else None
    return AutoclearStatus(
        backend="process",
        is_running=True,
        pid=pid,
        interval_seconds=interval,
        last_trigger=None,
        detail="Autoclear process backend running",
        pid_file=pid_file,
    )


def _status_from_process() -> AutoclearStatus:
    """Derive status from the detached worker-process backend when no system service owns execution."""
    pid_file = get_pid_file_path()
    active_pid = get_active_process_pid(warn_on_invalid=False)
    if active_pid is None:
        return _build_process_stopped_status("Autoclear not running", pid_file)
    return _build_process_running_status(active_pid, pid_file)


def install_autoclear_service(interval: str = "1h", system: bool = False) -> tuple[str, list[str]]:
    """
    Install the native background backend for this platform after parsing the human interval input.

    Flow:
        install-service -> install_autoclear_service
        install_autoclear_service
            -> _parse_interval
            -> _detect_platform
            -> _build_systemd_* | _install_systemd_*
    """
    # Application chooses the native backend that matches the current platform.
    interval_secs = _parse_interval(interval)
    platform = _detect_platform()

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
            -> _detect_platform
            -> _status_from_systemd | _status_from_process
    """
    # Linux prefers the native timer/service backend when it is installed.
    platform = _detect_platform()
    if platform == "linux":
        systemd_status = _status_from_systemd(system=False)
        if systemd_status.detail != "Autoclear systemd timer not installed":
            return systemd_status

    return _status_from_process()


def start_autoclear(interval: str) -> str:
    """
    Start autoclear using the backend that makes sense for the current platform.

    Flow:
        start -> start_autoclear
        start_autoclear
            -> _parse_interval
            -> _detect_platform
            -> start_service | spawn_detached_process
    """
    # One use-case, different infrastructure by platform.
    interval_secs = _parse_interval(interval)
    platform = _detect_platform()

    if platform == "linux":
        return start_service(interval_secs=interval_secs, system=False)

    pid = spawn_detached_process(interval_secs=interval_secs)
    return f"Autoclear started in background (PID {pid})"


def stop_autoclear() -> str:
    """
    Stop autoclear through the same backend-selection rules used for start/status.

    Flow:
        stop -> stop_autoclear
        stop_autoclear
            -> _detect_platform
            -> stop_service | stop_process
    """
    # Stop follows the same backend decision as start/status.
    platform = _detect_platform()

    if platform == "linux":
        systemd_status = _status_from_systemd(system=False)
        if systemd_status.detail != "Autoclear systemd timer not installed":
            return stop_service(system=False)

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
