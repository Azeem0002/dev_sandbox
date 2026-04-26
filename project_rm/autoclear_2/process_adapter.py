import subprocess
import sys
import time
from pathlib import Path

import psutil
from loguru import logger

from lifecycle_models import AutoclearStatus
from runtime_support import _get_platform_dirs, _get_worker_script_path


def _get_pid_file_path() -> Path:
    data_dir = Path(_get_platform_dirs().user_data_dir)
    try:
        data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        return data_dir / "autoclear.pid"
    except OSError as error:
        raise PermissionError("Failed to create directory") from error


def _read_pid_file() -> int | None:
    pid_file = _get_pid_file_path()

    try:
        return int(pid_file.read_text().strip())
    except (FileNotFoundError, ValueError, OSError):
        return None


def _is_process_running(pid: int) -> bool:
    return psutil.pid_exists(pid)


def _is_autoclear_process(pid: int) -> bool:
    try:
        process = psutil.Process(pid)
        cmdline = " ".join(process.cmdline())
        return "autoclear.py" in cmdline
    except OSError:
        return False


def _delete_pid_file() -> None:
    pid_file = _get_pid_file_path()

    try:
        pid_file.unlink(missing_ok=True)
    except OSError as error:
        logger.debug(f"Failed to delete pid file: {pid_file}")
        raise PermissionError(f"Failed to delete pid file: {pid_file}") from error


def _write_pid_file(pid: int) -> None:
    pid_file = _get_pid_file_path()
    logger.debug(f"Writing PID {pid} to {pid_file}")

    try:
        pid_file.write_text(str(pid))
    except OSError as error:
        raise RuntimeError(f"Failed to write to pid file: {pid_file}") from error


def _spawn_process(interval_secs: int) -> subprocess.Popen:
    command = [sys.executable, str(_get_worker_script_path()), str(interval_secs)]
    return subprocess.Popen(
        command,
        stdout=None,
        stderr=None,
        stdin=None,
        start_new_session=True,
    )


def _terminate_pid(pid: int) -> None:
    process = psutil.Process(pid)
    process.terminate()

    try:
        process.wait(timeout=3)
    except psutil.TimeoutExpired:
        process.kill()


def _status_from_process() -> AutoclearStatus:
    pid_file = _get_pid_file_path()
    pid = _read_pid_file() if pid_file.exists() else None

    if not pid_file.exists():
        return AutoclearStatus(
            backend="process",
            is_running=False,
            pid=None,
            interval_seconds=None,
            last_trigger=None,
            detail="Autoclear not running",
            pid_file=pid_file,
        )
    if pid is None:
        return AutoclearStatus(
            backend="process",
            is_running=False,
            pid=None,
            interval_seconds=None,
            last_trigger=None,
            detail="Invalid PID file",
            pid_file=pid_file,
        )
    if not _is_process_running(pid):
        return AutoclearStatus(
            backend="process",
            is_running=False,
            pid=pid,
            interval_seconds=None,
            last_trigger=None,
            detail="Dead PID file",
            pid_file=pid_file,
        )
    if not _is_autoclear_process(pid):
        return AutoclearStatus(
            backend="process",
            is_running=False,
            pid=pid,
            interval_seconds=None,
            last_trigger=None,
            detail="PID belongs to another process",
            pid_file=pid_file,
        )

    try:
        process = psutil.Process(pid)
        cmdline = process.cmdline()
        interval = int(cmdline[-1]) if len(cmdline) >= 2 and cmdline[-1].isdigit() else None
        return AutoclearStatus(
            backend="process",
            is_running=True,
            pid=pid,
            interval_seconds=interval,
            last_trigger=None,
            detail="Autoclear process backend running",
            pid_file=pid_file,
        )
    except Exception:
        return AutoclearStatus(
            backend="process",
            is_running=True,
            pid=pid,
            interval_seconds=None,
            last_trigger=None,
            detail="Autoclear process backend running",
            pid_file=pid_file,
        )


def _start_with_process(interval_secs: int) -> str:
    existing_pid = _read_pid_file()

    if existing_pid is not None:
        if _is_process_running(existing_pid) and _is_autoclear_process(existing_pid):
            return f"RUNNING: Autoclear already started with PID {existing_pid}"
        if not _is_process_running(existing_pid):
            _delete_pid_file()

    process = _spawn_process(interval_secs)
    if process.poll() is not None:
        raise RuntimeError("Autoclear failed to start")

    _write_pid_file(process.pid)
    time.sleep(0.3)
    logger.info(f"Autoclear started with process backend: interval={interval_secs}s pid={process.pid}")
    return f"STARTED: Autoclear process backend ({interval_secs}s interval, PID {process.pid})"


def _stop_with_process() -> str:
    pid_file = _get_pid_file_path()
    pid = _read_pid_file()

    if pid is None:
        return "STOPPED: Autoclear already stopped"
    if not _is_process_running(pid):
        _delete_pid_file()
        return "STOPPED: Removed stale PID file"
    if not _is_autoclear_process(pid):
        return "STOPPED: Refusing to kill unknown process"

    _terminate_pid(pid)
    _delete_pid_file()
    return "STOPPED: Autoclear process backend stopped"
