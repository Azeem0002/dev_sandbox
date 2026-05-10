"""Native service/task adapter for scheduler.

Linux uses one long-running systemd service. Windows uses Task Scheduler.
This layer knows how to install/control those native OS integrations.
"""

import getpass
import shlex
import subprocess
import sys
from pathlib import Path

try:
    from .platform_adapter import detect_platform
except ImportError:
    from platform_adapter import detect_platform


SYSTEMD_SERVICE_NAME = "scheduler.service"
WINDOWS_TASK_NAME = "Scheduler"

# Runtime shape:
# - Linux: one long-running systemd service keeps the scheduler daemon alive.
# - Windows: one Task Scheduler entry launches the scheduler background process at logon.

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


# Scheduler-specific path helper.
def _get_scheduler_script_path() -> Path:
    """Resolve the CLI entry script that the service/task should launch."""
    return Path(__file__).with_name("scheduler.py").resolve()


def _build_systemd_service(*, system: bool) -> str:
    """Build the unit file text for one long-running scheduler daemon."""
    service_lines = [
        "[Unit]",
        "Description=Job Scheduler",
        "After=network.target",
        "",
        "[Service]",
        "Type=simple",
    ]

    if system:
        service_lines.append(f"User={getpass.getuser()}")

    service_lines.extend([
        f"WorkingDirectory={_get_scheduler_script_path().parent}",
        f"ExecStart={_format_exec_args([sys.executable, str(_get_scheduler_script_path()), 'start'])}",
        "Environment=APP_ENV=prod",
        "Restart=on-failure",
        "RestartSec=10",
        "MemoryMax=200M",
        "CPUQuota=50%",
        "StandardOutput=journal",
        "StandardError=journal",
        "",
        "[Install]",
        f"WantedBy={'multi-user.target' if system else 'default.target'}",
        "",
    ])
    return "\n".join(service_lines)


def _build_windows_task_command() -> list[str]:
    """Build the `schtasks` command that launches the scheduler at user logon."""
    task_target = subprocess.list2cmdline([sys.executable, str(_get_scheduler_script_path()), "start"])
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


def _is_systemd_service_enabled(*, system: bool) -> bool:
    # `enabled` means the service is configured to start automatically.
    """Return whether systemd service enabled."""
    return _read_systemd_property(SYSTEMD_SERVICE_NAME, "UnitFileState", system=system) == "enabled"


def _install_windows_task() -> None:
    """Create the Windows Task Scheduler entry for the scheduler app."""
    result = _run_system_command(_build_windows_task_command())
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Failed to create Windows task")


# ============================================
# Project-specific extensions - long-running service backend
# ============================================
def _install_systemd_user(service_content: str) -> Path:
    """Write the service unit into the current user's systemd directory."""
    systemd_dir = _get_systemd_user_dir()
    systemd_dir.mkdir(parents=True, exist_ok=True)

    service_path = systemd_dir / SYSTEMD_SERVICE_NAME
    service_path.write_text(service_content, encoding="utf-8")
    return service_path


def _install_systemd_system(service_content: str) -> Path:
    """Install the service unit into `/etc/systemd/system` through `sudo tee`."""
    service_path = Path("/etc/systemd/system") / SYSTEMD_SERVICE_NAME
    result = _run_system_command(["sudo", "tee", str(service_path)], input_text=service_content)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Failed to install systemd service")
    return service_path


def _is_systemd_service_installed(*, system: bool) -> bool:
    # `loaded` means systemd can see and parse the unit file.
    """Return whether systemd service installed."""
    return _read_systemd_property(SYSTEMD_SERVICE_NAME, "LoadState", system=system) == "loaded"


def _start_with_systemd(*, system: bool) -> str:
    """Enable/start the scheduler service using systemd."""
    if not _is_systemd_service_installed(system=system):
        raise RuntimeError("Scheduler service is not installed. Run install-service first.")

    reload_result = _run_systemctl(["daemon-reload"], system=system)
    if reload_result.returncode != 0:
        raise RuntimeError(reload_result.stderr.strip() or "systemctl daemon-reload failed")

    if _is_systemd_service_enabled(system=system):
        start_result = _run_systemctl(["start", SYSTEMD_SERVICE_NAME], system=system)
        if start_result.returncode != 0:
            raise RuntimeError(start_result.stderr.strip() or "systemctl start service failed")
        return "STARTED: Scheduler systemd backend"

    enable_result = _run_systemctl(["enable", "--now", SYSTEMD_SERVICE_NAME], system=system)
    if enable_result.returncode != 0:
        raise RuntimeError(enable_result.stderr.strip() or "systemctl enable service failed")

    return "STARTED: Scheduler systemd backend"


def _stop_with_systemd(*, system: bool) -> str:
    """Disable/stop the scheduler service using systemd."""
    if not _is_systemd_service_installed(system=system):
        return "STOPPED: Scheduler already stopped"

    result = _run_systemctl(["disable", "--now", SYSTEMD_SERVICE_NAME], system=system)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Failed to stop scheduler service")

    return "STOPPED: Scheduler systemd backend stopped"


# ============================================
# Public adapter API - stable reusable surface
# ============================================
def install_service(*, interval_secs: int | None = None, system: bool = False) -> tuple[str, list[str]]:
    """Install the native OS service/task definition for the scheduler app."""
    del interval_secs

    platform = detect_platform()

    if platform == "windows":
        _install_windows_task()
        return (
            f"Windows Task '{WINDOWS_TASK_NAME}' created",
            ["Task will run when the current user logs on"],
        )

    if platform == "linux":
        service_content = _build_systemd_service(system=system)

        if system:
            service_path = _install_systemd_system(service_content)
            return (
                f"Installed system service at {service_path}",
                [
                    "sudo systemctl daemon-reload",
                    "Then run `scheduler start` to enable and start the installed service.",
                ],
            )

        service_path = _install_systemd_user(service_content)
        return (
            f"Installed user service at {service_path}",
            [
                "systemctl --user daemon-reload",
                f"loginctl enable-linger {getpass.getuser()}",
                "Then run `scheduler start` to enable and start the installed service.",
            ],
        )

    if platform == "mac":
        return (
            "macOS not yet supported",
            ["Use launchd manually or run with --foreground"],
        )

    raise RuntimeError(f"Unsupported platform: {platform}")


def service_is_installed(*, system: bool = False) -> bool:
    """Report whether the native service definition is installed."""
    platform = detect_platform()
    if platform == "linux":
        return _is_systemd_service_installed(system=system)
    return False


def start_service(*, interval_secs: int | None = None, system: bool = False) -> str:
    """Start the installed native service backend."""
    del interval_secs

    platform = detect_platform()
    if platform == "linux":
        return _start_with_systemd(system=system)

    if platform == "windows":
        raise RuntimeError("Windows scheduled task start is not exposed through service_adapter")

    raise RuntimeError(f"Unsupported platform: {platform}")


def stop_service(*, system: bool = False) -> str:
    """Stop the installed native service backend."""
    platform = detect_platform()
    if platform == "linux":
        return _stop_with_systemd(system=system)

    if platform == "windows":
        raise RuntimeError("Windows scheduled task stop is not exposed through service_adapter")

    raise RuntimeError(f"Unsupported platform: {platform}")


install_scheduler_service = install_service
