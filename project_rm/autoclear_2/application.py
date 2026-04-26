import getpass

import pytimeparse

from lifecycle_models import AutoclearStatus
from platform_adapter import _detect_platform
from process_adapter import _status_from_process, _start_with_process, _stop_with_process
from systemd_adapter import (
    _build_systemd_service,
    _build_systemd_timer,
    _install_systemd_system,
    _install_systemd_user,
    _status_from_systemd,
    _start_with_systemd,
    _stop_with_systemd,
)


def _parse_interval(value: str) -> int:
    if value.isdigit():
        return int(value)

    seconds = pytimeparse.parse(value)
    if seconds is None:
        raise ValueError(f"Invalid time format: {value}")
    if seconds <= 0:
        raise ValueError("Interval must be > 0")
    if seconds > 172800:
        raise ValueError("Interval too large. (max 2 days)")
    return int(seconds)


def install_autoclear_service(interval: str = "1h", system: bool = False) -> tuple[str, list[str]]:
    interval_secs = _parse_interval(interval)
    platform = _detect_platform()

    if platform == "linux":
        service_content = _build_systemd_service(system=system)
        timer_content = _build_systemd_timer(interval_secs, system=system)

        if system:
            service_path, timer_path = _install_systemd_system(service_content, timer_content)
            return (
                f"Installed system service at {service_path} and timer at {timer_path}",
                [
                    "sudo systemctl daemon-reload",
                    "Then run `autoclear start` to enable and start the installed timer.",
                ],
            )

        service_path, timer_path = _install_systemd_user(service_content, timer_content)
        return (
            f"Installed user service at {service_path} and timer at {timer_path}",
            [
                "systemctl --user daemon-reload",
                f"loginctl enable-linger {getpass.getuser()}",
                "Then run `autoclear start` to enable and start the installed timer.",
            ],
        )

    if platform == "windows":
        return ("Windows uses the process backend for autoclear", ["Use `start` to launch autoclear"])

    if platform == "mac":
        return ("macOS not yet supported for service install", ["Use `start` to launch autoclear"])

    raise RuntimeError(f"Unsupported platform: {platform}")


def get_autoclear_status() -> AutoclearStatus:
    platform = _detect_platform()
    if platform == "linux":
        systemd_status = _status_from_systemd(system=False)
        if systemd_status.detail != "Autoclear systemd timer not installed":
            return systemd_status

    return _status_from_process()


def start_autoclear(interval: str) -> str:
    interval_secs = _parse_interval(interval)
    platform = _detect_platform()

    if platform == "linux":
        return _start_with_systemd(interval_secs, system=False)

    return _start_with_process(interval_secs)


def stop_autoclear() -> str:
    platform = _detect_platform()

    if platform == "linux":
        systemd_status = _status_from_systemd(system=False)
        if systemd_status.detail != "Autoclear systemd timer not installed":
            return _stop_with_systemd(system=False)

    return _stop_with_process()


def restart_autoclear(interval: str) -> str:
    stop_autoclear()
    return start_autoclear(interval)
