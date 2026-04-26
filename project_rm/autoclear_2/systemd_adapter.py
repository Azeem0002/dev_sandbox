import getpass
import shlex
import subprocess
import sys
from pathlib import Path

from loguru import logger

from lifecycle_models import AutoclearStatus
from runtime_support import (
    SYSTEMD_SERVICE_NAME,
    SYSTEMD_TIMER_NAME,
    _get_worker_script_path,
)


def _format_exec_args(args: list[str]) -> str:
    return " ".join(shlex.quote(arg) for arg in args)


def _get_systemd_user_dir() -> Path:
    return Path.home() / ".config/systemd/user"


def _build_systemd_service(*, system: bool) -> str:
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
        f"WorkingDirectory={_get_worker_script_path().parent}",
        f"ExecStart={_format_exec_args([sys.executable, str(_get_worker_script_path()), '--once'])}",
        "Environment=APP_ENV=prod",
        "Nice=10",
        "",
        "[Install]",
        f"WantedBy={'multi-user.target' if system else 'default.target'}",
        "",
    ])
    return "\n".join(service_lines)


def _build_systemd_timer(interval_secs: int, *, system: bool) -> str:
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
    return subprocess.run(
        command,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_systemctl(args: list[str], *, system: bool) -> subprocess.CompletedProcess[str]:
    base = ["systemctl"]
    if not system:
        base.append("--user")
    return _run_system_command(base + args)


def _read_systemd_property(unit_name: str, property_name: str, *, system: bool) -> str | None:
    result = _run_systemctl(["show", unit_name, f"--property={property_name}", "--value"], system=system)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _is_systemd_timer_enabled(*, system: bool) -> bool:
    return _read_systemd_property(SYSTEMD_TIMER_NAME, "UnitFileState", system=system) == "enabled"


def _install_systemd_user(service_content: str, timer_content: str) -> tuple[Path, Path]:
    systemd_dir = _get_systemd_user_dir()
    systemd_dir.mkdir(parents=True, exist_ok=True)

    service_path = systemd_dir / SYSTEMD_SERVICE_NAME
    timer_path = systemd_dir / SYSTEMD_TIMER_NAME
    service_path.write_text(service_content)
    timer_path.write_text(timer_content)
    return service_path, timer_path


def _install_systemd_system(service_content: str, timer_content: str) -> tuple[Path, Path]:
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
    return _read_systemd_property(SYSTEMD_TIMER_NAME, "LoadState", system=system) == "loaded"


def _status_from_systemd(*, system: bool) -> AutoclearStatus:
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
    if not _is_systemd_timer_installed(system=system):
        return "STOPPED: Autoclear already stopped"

    timer_result = _run_systemctl(["disable", "--now", SYSTEMD_TIMER_NAME], system=system)
    if timer_result.returncode != 0:
        raise RuntimeError(timer_result.stderr.strip() or "Failed to disable systemd timer")

    service_result = _run_systemctl(["stop", SYSTEMD_SERVICE_NAME], system=system)
    if service_result.returncode != 0:
        raise RuntimeError(service_result.stderr.strip() or "Failed to stop systemd service")

    return "STOPPED: Autoclear systemd backend stopped"
