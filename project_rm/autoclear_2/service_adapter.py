"""Native service/task adapter for autoclear.

Linux uses a timer + service pair. Windows uses Task Scheduler.
This layer knows how to install/control those native OS integrations.
"""

import getpass
import shlex
import subprocess
import sys
from pathlib import Path

from loguru import logger

try:
    from .lifecycle_models import AutoclearStatus
    from .platform_adapter import detect_platform
    from .runtime_support import get_worker_script_path
except ImportError:
    from lifecycle_models import AutoclearStatus
    from platform_adapter import detect_platform
    from runtime_support import get_worker_script_path


SYSTEMD_SERVICE_NAME = "autoclear.service"
WINDOWS_TASK_NAME = "Autoclear"
SYSTEMD_TIMER_NAME = "autoclear.timer"

# Runtime shape:
# - Linux: a systemd timer acts as the alarm clock and triggers the autoclear service.
# - Windows: one Task Scheduler entry launches the long-running autoclear worker at logon.

# ============================================
# Service adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================
def _format_exec_args(args: list[str]) -> str:
    """Shell-quote each argument before embedding it into a systemd unit file."""
    return " ".join(shlex.quote(arg) for arg in args)


def _get_systemd_user_dir() -> Path:
    """Return the per-user systemd unit directory on Linux."""
    return Path.home() / ".config/systemd/user"


def _build_systemd_service(*, system: bool) -> str:
    """Build the worker service that clears the terminal once per trigger."""
    service_lines = [
        "[Unit]",
        "Description=Autoclear terminal worker",
        "",
        "[Service]",
        "Type=oneshot",
    ]

    if system:
        service_lines.append(f"User={getpass.getuser()}")

    service_lines.extend([
        f"WorkingDirectory={get_worker_script_path().parent}",
        f"ExecStart={_format_exec_args([sys.executable, str(get_worker_script_path()), '--once'])}",
        "Environment=APP_ENV=prod",
        "Nice=10",
        "",
        "[Install]",
        f"WantedBy={'multi-user.target' if system else 'default.target'}",
        "",
    ])
    return "\n".join(service_lines)


def _build_windows_task_command(interval_secs: int) -> list[str]:
    """Build the `schtasks` command that launches the autoclear worker at logon."""
    # Windows Task Scheduler cannot use "every N seconds" as flexibly as systemd timers.
    # Use a startup task that launches the long-running autoclear worker with its interval argument.
    task_target = subprocess.list2cmdline([sys.executable, str(get_worker_script_path()), str(interval_secs)])
    return [
        "schtasks",
        "/create",
        "/tn",
        WINDOWS_TASK_NAME,
        "/tr",
        task_target,
        "/sc",
        "onlogon",
        "/rl",
        "limited",
        "/f",
    ]


def _build_systemd_timer(interval_secs: int, *, system: bool) -> str:
    """Build the timer unit that acts like an alarm clock for the worker service."""
    del system
    timer_lines = [
        "[Unit]",
        "Description=Run autoclear on a fixed interval",
        "",
        "[Timer]",
        "OnBootSec=1m",
        f"OnUnitActiveSec={interval_secs}",
        f"Unit={SYSTEMD_SERVICE_NAME}",
        "Persistent=true",
        "AccuracySec=1s",
        "",
        "[Install]",
        "WantedBy=timers.target",
        "",
    ]
    return "\n".join(timer_lines)


def _run_system_command(command: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run one external OS command and capture stdout/stderr for adapter-level decisions."""
    return subprocess.run(
        command,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_systemctl(args: list[str], *, system: bool) -> subprocess.CompletedProcess[str]:
    # `systemctl --user` manages per-user units.
    # Plain `systemctl` manages system-wide units.
    """Run systemctl."""
    base = ["systemctl"]
    if not system:
        base.append("--user")
    return _run_system_command(base + args)


def _read_systemd_property(unit_name: str, property_name: str, *, system: bool) -> str | None:
    """Read one systemd unit property using `systemctl show`."""
    result = _run_systemctl(["show", unit_name, f"--property={property_name}", "--value"], system=system)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _is_systemd_timer_enabled(*, system: bool) -> bool:
    # For autoclear, the timer is the thing that gets enabled, not the oneshot service.
    """Return whether systemd timer enabled."""
    return _read_systemd_property(SYSTEMD_TIMER_NAME, "UnitFileState", system=system) == "enabled"


def _install_windows_task(interval_secs: int) -> None:
    """Create the Windows Task Scheduler entry for the autoclear worker."""
    result = _run_system_command(_build_windows_task_command(interval_secs))
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Failed to create Windows task")


# ============================================
# Project-specific extensions - timer backend
# ============================================
def _install_systemd_user(service_content: str, timer_content: str) -> tuple[Path, Path]:
    """Write both the worker service and timer into the current user's systemd directory."""
    systemd_dir = _get_systemd_user_dir()
    systemd_dir.mkdir(parents=True, exist_ok=True)

    service_path = systemd_dir / SYSTEMD_SERVICE_NAME
    timer_path = systemd_dir / SYSTEMD_TIMER_NAME
    service_path.write_text(service_content)
    timer_path.write_text(timer_content)
    return service_path, timer_path


def _install_systemd_system(service_content: str, timer_content: str) -> tuple[Path, Path]:
    """Install both the worker service and timer into `/etc/systemd/system`."""
    service_path = Path("/etc/systemd/system") / SYSTEMD_SERVICE_NAME
    timer_path = Path("/etc/systemd/system") / SYSTEMD_TIMER_NAME

    service_result = _run_system_command(["sudo", "tee", str(service_path)], input_text=service_content)
    if service_result.returncode != 0:
        raise RuntimeError(service_result.stderr.strip() or "Failed to install systemd service")

    timer_result = _run_system_command(["sudo", "tee", str(timer_path)], input_text=timer_content)
    if timer_result.returncode != 0:
        raise RuntimeError(timer_result.stderr.strip() or "Failed to install systemd timer")

    return service_path, timer_path


def _is_systemd_timer_installed(*, system: bool) -> bool:
    # `loaded` means systemd can see and parse the timer unit file.
    """Return whether systemd timer installed."""
    return _read_systemd_property(SYSTEMD_TIMER_NAME, "LoadState", system=system) == "loaded"


def _status_from_systemd(*, system: bool) -> AutoclearStatus:
    """Summarize the installed timer/service state into one app-facing status model."""
    if not _is_systemd_timer_installed(system=system):
        return AutoclearStatus(
            backend="systemd",
            is_running=False,
            pid=None,
            interval_seconds=None,
            last_trigger=None,
            detail="Autoclear systemd timer not installed",
        )

    timer_state = _read_systemd_property(SYSTEMD_TIMER_NAME, "ActiveState", system=system) or "unknown"
    service_state = _read_systemd_property(SYSTEMD_SERVICE_NAME, "ActiveState", system=system) or "unknown"
    last_trigger = _read_systemd_property(SYSTEMD_TIMER_NAME, "LastTriggerUSec", system=system) or "n/a"
    main_pid = _read_systemd_property(SYSTEMD_SERVICE_NAME, "MainPID", system=system) or ""
    pid = int(main_pid) if main_pid.isdigit() and int(main_pid) > 0 else None
    next_elapse = _read_systemd_property(SYSTEMD_TIMER_NAME, "NextElapseUSecRealtime", system=system)
    detail = f"timer={timer_state}, service={service_state}"
    return AutoclearStatus(
        backend="systemd",
        is_running=timer_state == "active",
        pid=pid,
        interval_seconds=None,
        last_trigger=last_trigger if last_trigger != "n/a" else next_elapse,
        detail=detail,
    )


def _start_with_systemd(interval_secs: int, *, system: bool) -> str:
    """Enable/start the autoclear timer backend using systemd."""
    del interval_secs

    if not _is_systemd_timer_installed(system=system):
        raise RuntimeError("Autoclear systemd timer is not installed. Run install-service first.")

    reload_result = _run_systemctl(["daemon-reload"], system=system)
    if reload_result.returncode != 0:
        raise RuntimeError(reload_result.stderr.strip() or "systemctl daemon-reload failed")

    if _is_systemd_timer_enabled(system=system):
        start_result = _run_systemctl(["start", SYSTEMD_TIMER_NAME], system=system)
        if start_result.returncode != 0:
            raise RuntimeError(start_result.stderr.strip() or "systemctl start timer failed")
        logger.info("Autoclear started with installed systemd timer")
        return "STARTED: Autoclear systemd backend"

    enable_result = _run_systemctl(["enable", "--now", SYSTEMD_TIMER_NAME], system=system)
    if enable_result.returncode != 0:
        raise RuntimeError(enable_result.stderr.strip() or "systemctl enable timer failed")

    logger.info("Autoclear started with installed systemd timer")
    return "STARTED: Autoclear systemd backend"


def _stop_with_systemd(*, system: bool) -> str:
    """Disable/stop the autoclear timer backend using systemd."""
    if not _is_systemd_timer_installed(system=system):
        return "STOPPED: Autoclear already stopped"

    timer_result = _run_systemctl(["disable", "--now", SYSTEMD_TIMER_NAME], system=system)
    if timer_result.returncode != 0:
        raise RuntimeError(timer_result.stderr.strip() or "Failed to disable systemd timer")

    service_result = _run_systemctl(["stop", SYSTEMD_SERVICE_NAME], system=system)
    if service_result.returncode != 0:
        raise RuntimeError(service_result.stderr.strip() or "Failed to stop systemd service")

    return "STOPPED: Autoclear systemd backend stopped"


# ============================================
# Public adapter API - stable reusable surface
# ============================================
def install_service(*, interval_secs: int | None = None, system: bool = False) -> tuple[str, list[str]]:
    """Install the native OS service/task definition for autoclear."""
    if interval_secs is None:
        raise ValueError("interval_secs is required to install autoclear service")

    platform = detect_platform()

    if platform == "windows":
        _install_windows_task(interval_secs)
        return (
            f"Windows Task '{WINDOWS_TASK_NAME}' created",
            ["Task will run when the current user logs on and launch the autoclear worker."],
        )

    if platform != "linux":
        if platform == "mac":
            return (
                "macOS not yet supported",
                ["Use launchd manually or run `autoclear start`."],
            )
        raise RuntimeError(f"Unsupported platform: {platform}")

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


def service_is_installed(*, system: bool = False) -> bool:
    """Report whether the native service definition is installed."""
    platform = detect_platform()
    if platform == "linux":
        return _is_systemd_timer_installed(system=system)
    return False


def start_service(*, interval_secs: int | None = None, system: bool = False) -> str:
    """Start the installed native service backend."""
    platform = detect_platform()
    if platform == "windows":
        raise RuntimeError("Windows task start is not exposed through service_adapter")
    if platform != "linux":
        raise RuntimeError(f"Unsupported platform: {platform}")
    if interval_secs is None:
        raise ValueError("interval_secs is required to start autoclear service")
    return _start_with_systemd(interval_secs, system=system)


def stop_service(*, system: bool = False) -> str:
    """Stop the installed native service backend."""
    platform = detect_platform()
    if platform == "windows":
        raise RuntimeError("Windows task stop is not exposed through service_adapter")
    if platform != "linux":
        raise RuntimeError(f"Unsupported platform: {platform}")
    return _stop_with_systemd(system=system)
