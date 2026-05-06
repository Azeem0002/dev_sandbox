import subprocess
import sys
import time
from pathlib import Path

import psutil
from loguru import logger

try:
    from .runtime_support import get_platform_dirs, get_worker_script_path
except ImportError:
    from runtime_support import get_platform_dirs, get_worker_script_path


# ============================================
# Process adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================
def _get_pid_file_path() -> Path:
    data_dir = Path(get_platform_dirs().user_data_dir)
    try:
        data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        return data_dir / "autoclear.pid"
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


def _is_managed_process(process: psutil.Process) -> bool:
    try:
        cmdline = process.cmdline()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False

    script_path = str(get_worker_script_path())
    return any(part == script_path or part.endswith("autoclear.py") for part in cmdline)


def _write_pid_file(pid: int) -> None:
    pid_file = _get_pid_file_path()
    logger.debug(f"Writing PID {pid} to {pid_file}")
    try:
        pid_file.write_text(str(pid), encoding="utf-8")
    except OSError as error:
        raise RuntimeError(f"Failed to write to pid file: {pid_file}") from error


def _remove_pid_file() -> None:
    pid_file = _get_pid_file_path()
    try:
        pid_file.unlink(missing_ok=True)
    except OSError as error:
        logger.debug(f"Failed to delete pid file: {pid_file}")
        raise PermissionError(f"Failed to delete pid file: {pid_file}") from error


def _get_active_process_pid(*, warn_on_invalid: bool = True) -> int | None:
    pid = _read_pid_file(warn_on_invalid=warn_on_invalid)
    if pid is None:
        return None

    process = _get_process(pid)
    if process is not None and _is_managed_process(process):
        return process.pid

    logger.warning(f"Removing stale PID file for invalid autoclear process {pid}")
    try:
        _remove_pid_file()
    except PermissionError as error:
        logger.warning(str(error))
    return None


def _spawn_detached_process(interval_secs: int) -> int:
    existing_pid = _get_active_process_pid()
    if existing_pid is not None:
        raise RuntimeError(f"Autoclear is already running (PID {existing_pid})")

    process = subprocess.Popen(
        [sys.executable, str(get_worker_script_path()), str(interval_secs)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,  # "Close all file descriptors before running the child process."
    )

    deadline = time.time() + 5
    while time.time() < deadline:
        active_pid = _get_active_process_pid(warn_on_invalid=False)
        if active_pid is not None:
            return active_pid

        exit_code = process.poll()
        if exit_code is not None:
            raise RuntimeError(f"Detached autoclear failed to start (exit {exit_code})")

        if process.pid:
            _write_pid_file(process.pid)

        time.sleep(0.1)

    raise RuntimeError("Detached autoclear did not create a PID file in time")


def _read_interval_from_process(process: psutil.Process) -> int | None:
    try:
        cmdline = process.cmdline()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None

    if cmdline and cmdline[-1].isdigit():
        return int(cmdline[-1])
    return None


def _stop_process(wait: bool = True) -> bool:
    active_pid = _get_active_process_pid()
    if active_pid is None:
        logger.info("Autoclear is not running")
        return False

    try:
        process = psutil.Process(active_pid)
        process.terminate()
    except psutil.NoSuchProcess:
        _remove_pid_file()
        logger.info("Autoclear is not running")
        return False

    logger.info(f"Sent stop signal to autoclear process {active_pid}")

    if wait:
        try:
            process.wait(timeout=10)
            _remove_pid_file()
            return True
        except psutil.TimeoutExpired:
            logger.warning(f"Autoclear process {active_pid} did not exit within timeout")
            process.kill()
            process.wait(timeout=5)
            _remove_pid_file()
            return True

    return True


# ============================================
# Public adapter API - stable reusable surface
# ============================================
def get_pid_file_path() -> Path:
    return _get_pid_file_path()


def read_pid_file(*, warn_on_invalid: bool = True) -> int | None:
    return _read_pid_file(warn_on_invalid=warn_on_invalid)


def get_process(pid: int) -> psutil.Process | None:
    return _get_process(pid)


def is_managed_process(process: psutil.Process) -> bool:
    return _is_managed_process(process)


def write_pid_file(pid: int) -> None:
    _write_pid_file(pid)


def remove_pid_file() -> None:
    _remove_pid_file()


def get_active_process_pid(*, warn_on_invalid: bool = True) -> int | None:
    return _get_active_process_pid(warn_on_invalid=warn_on_invalid)


def spawn_detached_process(*, interval_secs: int | None = None) -> int:
    if interval_secs is None:
        raise ValueError("interval_secs is required for autoclear background process")
    return _spawn_detached_process(interval_secs)


def read_process_interval_seconds(process: psutil.Process) -> int | None:
    return _read_interval_from_process(process)


def stop_process(wait: bool = True) -> bool:
    return _stop_process(wait=wait)


_is_autoclear_process = _is_managed_process
_get_active_autoclear_pid = _get_active_process_pid
_spawn_detached_autoclear = _spawn_detached_process
stop_autoclear_process = _stop_process
