"""Linux systemd adapter for scheduler.

This module owns systemd unit text and systemctl calls.
service_adapter.py stays as the cross-platform facade.
"""

import getpass
import shlex
import subprocess
import sys
from pathlib import Path


SYSTEMD_SERVICE_NAME = "scheduler.service"


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


def _get_scheduler_script_path() -> Path:
    """Resolve the CLI entry script that the service should launch."""
    return Path(__file__).with_name("scheduler.py").resolve()


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
        # System services run outside the current user session, so add the target user explicitly.
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


def _is_systemd_service_enabled(*, system: bool) -> bool:
    """Return whether the systemd service is enabled."""
    # `enabled` means the service is configured to start automatically.
    return _read_systemd_property(SYSTEMD_SERVICE_NAME, "UnitFileState", system=system) == "enabled"


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
    # `sudo tee <path>` lets us write privileged files while still feeding content from Python stdin.
    result = _run_system_command(["sudo", "tee", str(service_path)], input_text=service_content)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Failed to install systemd service")
    return service_path


def _is_systemd_service_installed(*, system: bool) -> bool:
    """Return whether systemd can see and parse the service unit file."""
    return _read_systemd_property(SYSTEMD_SERVICE_NAME, "LoadState", system=system) == "loaded"


def _start_with_systemd(*, system: bool) -> str:
    """Enable/start the scheduler service using systemd."""
    if not _is_systemd_service_installed(system=system):
        raise RuntimeError("Scheduler service is not installed. Run install-service first.")

    # daemon-reload tells systemd to rescan unit files after install/update.
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
def install_systemd_service(*, system: bool = False) -> tuple[str, list[str]]:
    """Install the scheduler systemd service."""
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


def is_systemd_service_installed(*, system: bool = False) -> bool:
    """Report whether the scheduler systemd service is installed."""
    return _is_systemd_service_installed(system=system)


def start_systemd_service(*, system: bool = False) -> str:
    """Start the installed scheduler systemd backend."""
    return _start_with_systemd(system=system)


def stop_systemd_service(*, system: bool = False) -> str:
    """Stop the installed scheduler systemd backend."""
    return _stop_with_systemd(system=system)
