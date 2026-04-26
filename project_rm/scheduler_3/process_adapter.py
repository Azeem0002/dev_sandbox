import subprocess
import sys
import time
from pathlib import Path

import psutil
from loguru import logger

try:
    from .runtime_support import _get_platform_dirs
except ImportError:
    from runtime_support import _get_platform_dirs


def _get_pid_file_path() -> Path:
    data_dir = Path(_get_platform_dirs().user_data_dir)
    try:
        data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        return data_dir / "scheduler.pid"
    except OSError as error:
        raise PermissionError("Failed to create directory") from error


def _read_pid_file(*, warn_on_invalid: bool = True) -> int | None:
    pid_file = _get_pid_file_path()
    try:
        raw_pid = pid_file.read_text(encoding="utf-8").strip()
        return int(raw_pid)
    except FileNotFoundError:
        return None
    except (ValueError, PermissionError):
        if warn_on_invalid:
            logger.warning(f"Invalid PID file contents at {pid_file}")
        pid_file.unlink(missing_ok=True)
        return None


def _is_scheduler_process(process: psutil.Process) -> bool:
    try:
        cmdline = process.cmdline()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False

    script_path = str(Path(__file__).with_name("scheduler.py").resolve())
    return any(part == script_path or part.endswith("scheduler.py") for part in cmdline)


def _get_process(pid: int) -> psutil.Process | None:
    try:
        process = psutil.Process(pid)
        if not process.is_running():
            return None
        if process.status() == psutil.STATUS_ZOMBIE:
            return None
        return process
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None


def _write_pid_file(pid: int) -> None:
    _get_pid_file_path().write_text(str(pid), encoding="utf-8")


def _remove_pid_file() -> None:
    _get_pid_file_path().unlink(missing_ok=True)


def _get_active_scheduler_pid(*, warn_on_invalid: bool = True) -> int | None:
    pid = _read_pid_file(warn_on_invalid=warn_on_invalid)
    if pid is None:
        return None

    process = _get_process(pid)
    if process is not None and _is_scheduler_process(process):
        return process.pid

    logger.warning(f"Removing stale PID file for invalid scheduler process {pid}")
    _remove_pid_file()
    return None


def _spawn_detached_scheduler() -> int:
    existing_pid = _get_active_scheduler_pid()
    if existing_pid is not None:
        raise RuntimeError(f"Scheduler is already running (PID {existing_pid})")

    script_path = Path(__file__).with_name("scheduler.py").resolve()
    process = subprocess.Popen(
        [sys.executable, str(script_path), "start", "--foreground"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )

    deadline = time.time() + 5
    while time.time() < deadline:
        active_pid = _get_active_scheduler_pid(warn_on_invalid=False)
        if active_pid is not None:
            return active_pid

        exit_code = process.poll()
        if exit_code is not None:
            raise RuntimeError(f"Detached scheduler failed to start (exit {exit_code})")

        time.sleep(0.1)

    raise RuntimeError("Detached scheduler did not create a PID file in time")


def stop_scheduler_process(wait: bool = True) -> bool:
    active_pid = _get_active_scheduler_pid()
    if active_pid is None:
        logger.info("Scheduler is not running")
        return False

    try:
        process = psutil.Process(active_pid)
        process.terminate()
    except psutil.NoSuchProcess:
        _remove_pid_file()
        logger.info("Scheduler is not running")
        return False

    logger.info(f"Sent stop signal to scheduler process {active_pid}")

    if wait:
        try:
            process.wait(timeout=10)
            _remove_pid_file()
            return True
        except psutil.TimeoutExpired:
            logger.warning(f"Scheduler process {active_pid} did not exit within timeout")

    return True
