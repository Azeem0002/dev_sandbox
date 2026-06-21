"""Linux systemd adapter for autoclear.

This module owns systemd unit text, systemctl calls, and systemd status parsing.
service_adapter.py stays as the cross-platform facade.
"""

import getpass
import shlex
import subprocess
import sys
from pathlib import Path

from loguru import logger

try:
    from .lifecycle_models import AutoclearStatus
    from .runtime_adapter import get_worker_script_path
except ImportError:
    from lifecycle_models import AutoclearStatus
    from runtime_adapter import get_worker_script_path


SYSTEMD_SERVICE_NAME = "autoclear.service"
SYSTEMD_TIMER_NAME = "autoclear.timer"


# ============================================
# Systemd adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================
def _format_exec_args(args: list[str]) -> str:
    """Shell-quote each argument before embedding it into a systemd unit file."""
    # systemd unit files store ExecStart as shell-like text, not as a Python argv list.
    return " ".join(shlex.quote(arg) for arg in args)


def _get_systemd_user_dir() -> Path:
    """Return the per-user systemd unit directory on Linux."""
    return Path.home() / ".config/systemd/user"


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
    """Run systemctl for either user-level or system-level units."""
    # `systemctl --user` manages per-user units.
    # Plain `systemctl` manages system-wide units.
    # system means user-level or system-wide. system-wide requires sudo
    base = ["systemctl"]
    if not system:
        base.append("--user")
    return _run_system_command(base + args)


def _read_systemd_property(unit_name: str, property_name: str, *, system: bool) -> str | None:
    """Read one systemd unit property using `systemctl show`."""
    # `systemctl show --property=X --value` is cleaner for scripts than parsing human-oriented status output.
    result = _run_systemctl(["show", unit_name, f"--property={property_name}", "--value"], system=system)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


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
        # System services run outside the current user session, so add the target user explicitly.
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


def _build_systemd_timer(interval_secs: int) -> str:
    """Build the timer unit that acts like an alarm clock for the worker service."""
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


def _is_systemd_timer_enabled(*, system: bool) -> bool:
    """Return whether the systemd timer is enabled."""
    # For autoclear, the timer is the thing that gets enabled, not the oneshot service.
    return _read_systemd_property(SYSTEMD_TIMER_NAME, "UnitFileState", system=system) == "enabled"


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

    # `sudo tee <path>` lets us write privileged files while still feeding content from Python stdin.
    service_result = _run_system_command(["sudo", "tee", str(service_path)], input_text=service_content)
    if service_result.returncode != 0:
        raise RuntimeError(service_result.stderr.strip() or "Failed to install systemd service")

    timer_result = _run_system_command(["sudo", "tee", str(timer_path)], input_text=timer_content)
    if timer_result.returncode != 0:
        raise RuntimeError(timer_result.stderr.strip() or "Failed to install systemd timer")

    return service_path, timer_path


def _is_systemd_timer_installed(*, system: bool) -> bool:
    """Return whether systemd can see and parse the timer unit file."""
    return _read_systemd_property(SYSTEMD_TIMER_NAME, "LoadState", system=system) == "loaded"


def _get_status_from_systemd(*, system: bool) -> AutoclearStatus:
    """Summarize the installed timer/service state into one app-facing status model."""
    # Read raw unit properties once here so the rest of the app can consume one typed status object.
    if not _is_systemd_timer_installed(system=system):
        # This factory stays in the adapter because "systemd timer not installed"
        # is infrastructure knowledge, not a generic model rule.
        return AutoclearStatus(
            backend="systemd",  # The adapter checked the systemd backend.
            is_running=False,  # Missing timer means systemd cannot be running this app.
            pid=None,  # No service process exists when the timer is missing.
            interval_seconds=None,  # systemd status does not expose our original interval cleanly here.
            last_trigger=None,  # Missing timer means no trigger metadata exists.
            detail="Autoclear systemd timer not installed",
        )

    # Timer state answers "is the schedule active?"
    timer_state = _read_systemd_property(SYSTEMD_TIMER_NAME, "ActiveState", system=system) or "unknown"
    # Service state answers "what happened to the worker service?"
    service_state = _read_systemd_property(SYSTEMD_SERVICE_NAME, "ActiveState", system=system) or "unknown"
    # LastTriggerUSec is useful after the timer has fired at least once.
    last_trigger = _read_systemd_property(SYSTEMD_TIMER_NAME, "LastTriggerUSec", system=system) or "n/a"
    # MainPID is "0" for inactive oneshot services, so treat non-positive values as no PID.
    main_pid = _read_systemd_property(SYSTEMD_SERVICE_NAME, "MainPID", system=system) or ""
    pid = int(main_pid) if main_pid.isdigit() and int(main_pid) > 0 else None
    # NextElapseUSecRealtime gives the next scheduled trigger when there is no last trigger yet.
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


def _start_with_systemd(*, system: bool) -> str:
    """Enable/start the autoclear timer backend using systemd."""
    if not _is_systemd_timer_installed(system=system):
        raise RuntimeError("Autoclear systemd timer is not installed. Run install-service first.")

    # daemon-reload tells systemd to re-scan unit files after install/update.
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
def install_systemd_service(*, interval_secs: int, system: bool = False) -> tuple[str, list[str]]:
    """Install the autoclear systemd service/timer pair."""
    service_content = _build_systemd_service(system=system)
    timer_content = _build_systemd_timer(interval_secs)

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


def is_systemd_service_installed(*, system: bool = False) -> bool:
    """Report whether the autoclear systemd timer is installed."""
    return _is_systemd_timer_installed(system=system)


def start_systemd_service(*, interval_secs: int | None = None, system: bool = False) -> str:
    """Start the installed autoclear systemd backend."""
    del interval_secs
    return _start_with_systemd(system=system)


def stop_systemd_service(*, system: bool = False) -> str:
    """Stop the installed autoclear systemd backend."""
    return _stop_with_systemd(system=system)


def get_status_from_systemd(*, system: bool) -> AutoclearStatus:
    """Return autoclear status from the systemd backend."""
    return _get_status_from_systemd(system=system)
