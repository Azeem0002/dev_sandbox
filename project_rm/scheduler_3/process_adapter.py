"""Detached-process adapter for scheduler.

This module owns PID files, daemon discovery, spawning, and stopping.
It hides OS/process details behind a stable app-facing adapter surface.
"""

import subprocess
import sys
import time
from pathlib import Path

import psutil
from loguru import logger

try:
    from .runtime_adapter import get_platform_dirs
except ImportError:
    from runtime_adapter import get_platform_dirs


# ============================================
# Process adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================
def _get_pid_file_path() -> Path:
    """Return the app-owned PID file location for the scheduler daemon."""
    data_dir = Path(get_platform_dirs().user_data_dir)
    # Keep path getters pure: do not create directories here.
    # The write step owns the side effect of making the parent folder.
    return data_dir / "scheduler.pid"


def _read_pid_file(*, warn_on_invalid: bool = True) -> int | None:
    """Read the stored scheduler PID, returning `None` when the file is missing or invalid."""
    pid_file = _get_pid_file_path()
    try:
        # read_text(...).strip(): read file contents as text and remove whitespace/newline.
        raw_pid = pid_file.read_text(encoding="utf-8").strip()
        # int("1234") -> 1234. Raises ValueError if the file contains invalid text.
        return int(raw_pid)
    except FileNotFoundError:
        return None
    except (ValueError, PermissionError):
        if warn_on_invalid:
            logger.warning(f"Invalid PID file contents at {pid_file}")
        pid_file.unlink(missing_ok=True)
        return None


def _get_process(pid: int) -> psutil.Process | None:
    """Return a live process handle for `pid`, or `None` if it no longer represents a usable process."""
    try:
        # psutil.Process(pid): lightweight handle for querying/managing a running OS process.
        process = psutil.Process(pid)
        if not process.is_running():
            return None
        if process.status() == psutil.STATUS_ZOMBIE:
            return None
        return process
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None


def _is_managed_process(process: psutil.Process) -> bool:
    """Return whether this OS process is the scheduler daemon managed by this project."""
    try:
        cmdline = process.cmdline()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False

    script_path = str(Path(__file__).with_name("scheduler.py").resolve())
    return any(part == script_path or part.endswith("scheduler.py") for part in cmdline)


def _write_pid_file(pid: int) -> None:
    """Persist the daemon PID so later commands can find and manage the running process."""
    pid_file = _get_pid_file_path()
    # Writing is a side-effecting responsibility, so parent-dir creation belongs here.
    pid_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    logger.debug(f"Writing PID {pid} to {pid_file}")
    # PID file = small text file that records "which process currently owns this app".
    pid_file.write_text(str(pid), encoding="utf-8")


def _remove_pid_file() -> None:
    """Delete the PID file to prevent stale daemon pointers after shutdown/crashes."""
    pid_file = _get_pid_file_path()
    pid_file.unlink(missing_ok=True)


def _get_active_process_pid_status(*, warn_on_invalid: bool = True) -> int | None:
    """Return the active scheduler PID only when the PID file points to a real managed daemon."""
    pid = _read_pid_file(warn_on_invalid=warn_on_invalid)
    if pid is None:
        return None

    # Two-step check:
    # 1. does a process with this PID still exist?
    # 2. is it actually *our* scheduler daemon, not some unrelated reused PID?
    process = _get_process(pid)
    if process is not None and _is_managed_process(process):
        return process.pid

    logger.warning(f"Removing stale PID file for invalid scheduler process {pid}")
    try:
        _remove_pid_file()
    except OSError as error:
        logger.warning(str(error))
    return None


def _spawn_detached_process() -> int:
    """Launch the scheduler in a detached child process and wait until startup becomes observable."""
    existing_pid = _get_active_process_pid_status()
    if existing_pid is not None:
        raise RuntimeError(f"Scheduler is already running (PID {existing_pid})")

    # Return the standalone worker entrypoint that detached processes and services must launch.
    script_path = Path(__file__).with_name("scheduler.py").resolve()

    process = subprocess.Popen(
        [sys.executable, str(script_path), "start", "--foreground"],
        # DEVNULL: child inherits no usable stdin/stdout/stderr from this terminal.
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        # start_new_session=True: detach child from the current terminal/session.
        start_new_session=True,
        close_fds=True,
    )

    deadline = time.time() + 5
    while time.time() < deadline:
        active_pid = _get_active_process_pid_status(warn_on_invalid=False)
        if active_pid is not None:
            return active_pid

        exit_code = process.poll()
        if exit_code is not None:
            raise RuntimeError(f"Detached scheduler failed to start (exit {exit_code})")

        time.sleep(0.1)

    raise RuntimeError("Detached scheduler did not create a PID file in time")


def _read_interval_from_process(process: psutil.Process) -> int | None:
    """Keep the shared adapter API shape; scheduler has no process interval, so return `None`."""
    del process
    return None


def _stop_process(wait: bool = True) -> bool:
    """Stop the running scheduler process and optionally wait for it to exit cleanly."""
    active_pid = _get_active_process_pid_status()
    if active_pid is None:
        logger.info("Scheduler is not running")
        return False

    try:
        process = psutil.Process(active_pid)
        # terminate() asks nicely (SIGTERM on Unix). kill() is the hard fallback.
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
    """Public wrapper for the scheduler PID file location."""
    return _get_pid_file_path()


def read_pid_file(*, warn_on_invalid: bool = True) -> int | None:
    """Public wrapper for reading the stored scheduler PID."""
    return _read_pid_file(warn_on_invalid=warn_on_invalid)


def get_process(pid: int) -> psutil.Process | None:
    """Public wrapper for resolving a live process handle from a PID."""
    return _get_process(pid)


def is_managed_process(process: psutil.Process) -> bool:
    """Public wrapper for checking whether a process belongs to this scheduler app."""
    return _is_managed_process(process)


def write_pid_file(pid: int) -> None:
    """Public wrapper for persisting the scheduler PID file."""
    _write_pid_file(pid)


def remove_pid_file() -> None:
    """Public wrapper for deleting the scheduler PID file."""
    _remove_pid_file()


def get_active_process_pid_status(*, warn_on_invalid: bool = True) -> int | None:
    """Public wrapper for resolving the currently running scheduler PID."""
    return _get_active_process_pid_status(warn_on_invalid=warn_on_invalid)


def spawn_detached_process(*, interval_secs: int | None = None) -> int:
    """Public wrapper for detached startup using the shared cross-project adapter signature."""
    # Scheduler does not need an interval, so it accepts and ignores the shared parameter.
    del interval_secs
    return _spawn_detached_process()


def read_process_interval_seconds(process: psutil.Process) -> int | None:
    """Public wrapper for interval inspection; scheduler always returns `None` here."""
    return _read_interval_from_process(process)


def stop_process(wait: bool = True) -> bool:
    """Public wrapper for stopping the scheduler background process."""
    return _stop_process(wait=wait)
