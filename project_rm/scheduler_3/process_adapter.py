import subprocess
import sys
import time
from pathlib import Path

import psutil
from loguru import logger

try:
    from .runtime_support import get_platform_dirs
except ImportError:
    from runtime_support import get_platform_dirs


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
        # mode = for current user only
        return data_dir / "scheduler.pid"
    except OSError as e:
        raise PermissionError("Failed to create directory") from e


def _read_pid_file(*, warn_on_invalid: bool = True) -> int | None:
    # Without *, you could accidentally pass positional arguments. With *, the caller MUST be explicit about what True means.
    
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


def _is_managed_process(process: psutil.Process) -> bool:
    try:
        cmdline = process.cmdline()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False

    # __file__ → full path to current file path: pathlib.Path
    # .with_name() → replace filename: pathlib.Path
    # .resolve() → absolute path(full address from root e.g /home/az/dev_sandbox/project_rm/scheduler.py)
    # 👉 Build full path to scheduler.py
    script_path = str(Path(__file__).with_name("scheduler.py").resolve())
    return any(part == script_path or part.endswith("scheduler.py") for part in cmdline)
    # Translation: "Is ANY part of the command line exactly our script path OR ends with scheduler.py?"


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
    pid_file = _get_pid_file_path()
    logger.debug(f"Writing PID {pid} to {pid_file}")

    try:
        pid_file.write_text(str(pid), encoding="utf-8")
    except OSError as e:
        raise RuntimeError(f"Failed to write to pid file: {pid_file}") from e


def _remove_pid_file() -> None:
    pid_file = _get_pid_file_path()

    try:
        pid_file.unlink(missing_ok=True)
    except OSError as error:
        logger.debug(f"Failed to delete pid file: {pid_file}")
        raise PermissionError(f"Failed to delete pid file: {pid_file}") from error


def _get_active_process_pid(*, warn_on_invalid: bool = True) -> int | None:
    # Without *, you could accidentally pass positional arguments. With *, the caller MUST be explicit about what True means.

    pid = _read_pid_file(warn_on_invalid=warn_on_invalid)
    if pid is None:
        return None

    process = _get_process(pid)
    if process is not None and _is_managed_process(process):
        return process.pid

    logger.warning(f"Removing stale PID file for invalid scheduler process {pid}")
    try:
        _remove_pid_file()
    except PermissionError as error:
        logger.warning(str(error))
    return None


def _read_interval_from_process(process: psutil.Process) -> int | None:
    # Scheduler background workers do not carry an interval argument in their process command line.
    # Keep the public adapter function for the shared mental map, but return None for this project.
    del process
    return None


def _spawn_detached_process() -> int:
    existing_pid = _get_active_process_pid()
    if existing_pid is not None:
        raise RuntimeError(f"Scheduler is already running (PID {existing_pid})")

    script_path = Path(__file__).with_name("scheduler.py").resolve()
    process = subprocess.Popen(
        [sys.executable, str(script_path), "start", "--foreground"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,  # "Close all file descriptors before running the child process." 
        # close_fds: Don’t let the child process inherit open files from the parent. scheduler and jobs won't share resources
        
    )
    # sys.executable(cross-platform)  # → linux: "/usr/bin/python3". On Windows: C:\Python312\python.exe

    deadline = time.time() + 5  # wait max 5 seconds
    while time.time() < deadline:  # "Keep checking until deadline"
        active_pid = _get_active_process_pid(warn_on_invalid=False)
        # "Check PID file (don't warn if missing)" → check if scheduler started

        if active_pid is not None:
            return active_pid

        exit_code = process.poll() # "Did the process crash?"
        if exit_code is not None:
            raise RuntimeError(f"Detached scheduler failed to start (exit {exit_code})")

        time.sleep(0.1)  # Wait 100ms between checks → avoid CPU burn

    raise RuntimeError("Detached scheduler did not create a PID file in time")


def _stop_process(wait: bool = True) -> bool:
    active_pid = _get_active_process_pid()
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
    del interval_secs
    return _spawn_detached_process()


def read_process_interval_seconds(process: psutil.Process) -> int | None:
    return _read_interval_from_process(process)


def stop_process(wait: bool = True) -> bool:
    return _stop_process(wait=wait)


_is_scheduler_process = _is_managed_process
_get_active_scheduler_pid = _get_active_process_pid
_spawn_detached_scheduler = _spawn_detached_process
stop_scheduler_process = _stop_process
