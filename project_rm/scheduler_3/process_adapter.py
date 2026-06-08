"""Detached-process adapter for scheduler.

This module owns PID files, daemon discovery, spawning, and stopping.
It hides process-management details behind a stable adapter surface.
"""

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
    # `platformdirs` gives the app-owned data directory for the current OS/user.
    """Return the app-owned PID file location for the scheduler daemon."""
    data_dir = Path(get_platform_dirs().user_data_dir)
    # Keep path getters pure: do not create directories here.
    # The write step owns the side effect of making the parent folder.
    return data_dir / "scheduler.pid"


def _read_pid_file(*, warn_on_invalid: bool = True) -> int | None:
    # Without *, you could accidentally pass positional arguments. With *, the caller MUST be explicit about what True means.
    
    """Read the stored scheduler PID, returning `None` when the file is missing or junk."""
    pid_file = _get_pid_file_path()
    try:
        # read_text(...).strip(): read file contents as text and remove whitespace/newline.
        raw_pid = pid_file.read_text(encoding="utf-8").strip() # .read_text() makes it a str
        
        # int("1234") -> 1234. Raises ValueError if the file contains junk.
        return int(raw_pid)
    except FileNotFoundError:
        return None
    except (ValueError, PermissionError):
        if warn_on_invalid:
            logger.warning(f"Invalid PID file contents at {pid_file}")
        pid_file.unlink(missing_ok=True)
        return None
    
    

def _get_process(pid: int) -> psutil.Process | None:  # A live interface to OS process.
    """Return a live process handle for `pid`, or `None` if the process is gone/unusable for this OS."""
    # Is there someone in Room 1234? or does this process exist and look alive?
    try:
        # psutil.Process(pid): lightweight handle for querying/managing a running OS process.
        process = psutil.Process(pid) # process object. Full process info (memory, CPU, cmdline)
        if not process.is_running():
            return None
        if process.status() == psutil.STATUS_ZOMBIE: # status + safety
            return None
        return process
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None
    
def _is_managed_process(process: psutil.Process) -> bool:
    """Return whether this OS process is actually this project's scheduler process."""
    
    try: # only risky code in try. only wrap what can actually fail
        cmdline = process.cmdline() # Call method ON the process object 
        # cmdline() contains executables and args only, no pid
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False

    # __file__ → relative path to current file path: pathlib.Path
    # .with_name() → replace filename: pathlib.Path
    # .resolve() → absolute path(full address from root e.g /home/az/dev_sandbox/project_rm/scheduler.py)
    # 👉 Converts relative path to absolute path
    script_path = str(Path(__file__).with_name("scheduler.py").resolve())
    return any(part == script_path or part.endswith("scheduler.py") for part in cmdline)
    # Translation: "Is ANY part of the command line exactly our script path OR ends with scheduler.py?". any returns iterables of booleans.


def _write_pid_file(pid: int) -> None:
    """Persist the daemon PID so later commands can find the running scheduler process."""
    # This function is not answering a question.
    # It is performing an action. A doer not an answer
    
    pid_file = _get_pid_file_path()
    # Writing is a side-effecting responsibility, so parent-dir creation belongs here.
    pid_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True) # make sure the directory exists before writing
    logger.debug(f"Writing PID {pid} to {pid_file}")
    # PID file = small text file that records "which process currently owns this app".
    pid_file.write_text(str(pid), encoding="utf-8") 
    # UTF-8 is the universal standard that handles all languages. How text is converted to bytes
    return None
    # The -> None tells you: "I'm a doer, not an answerer."

def _remove_pid_file() -> None:
    """Delete the PID file so stale process pointers do not survive shutdown."""
    pid_file = _get_pid_file_path()
    pid_file.unlink(missing_ok=True)


def _get_active_process_pid(*, warn_on_invalid: bool = True) -> int | None:
    # Without *, you could accidentally pass positional arguments. With *, the caller MUST be explicit about what True means.

    """Return the active scheduler PID only when the PID file points to a real managed process."""
    pid = _read_pid_file(warn_on_invalid=warn_on_invalid)
    if pid is None:
        return None

    # Two-step check:
    # 1. does a process with this PID still exist?
    # 2. is it actually *our* scheduler process, not some unrelated reused PID?
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
    """Launch the scheduler in a detached child process and wait until it proves it started."""
    existing_pid = _get_active_process_pid()
    if existing_pid is not None:
        raise RuntimeError(f"Scheduler is already running (PID {existing_pid})")

    # Return the standalone worker entrypoint that detached processes and services must launch.
    script_path = Path(__file__).with_name("scheduler.py").resolve()
    
    process = subprocess.Popen(
        [sys.executable, str(script_path), "start", "--foreground"],
        # DEVNULL: child inherits no usable stdin/stdout/stderr from this terminal.
        # disconnecting the child process from the terminal or "throw it away"
        stdout=subprocess.DEVNULL, # child cannot hear keyboard input
        stderr=subprocess.DEVNULL, # child cannot print to terminal
        stdin=subprocess.DEVNULL, # child errors disappear
        start_new_session=True, # detach child from the current terminal/session.
        close_fds=True,  # "Close all file descriptors before running the child process." 
        # close_fds: Don’t let the child process inherit open files from the parent. scheduler and jobs won't share resources
        
    )
    # sys.executable(cross-platform)  # → linux: "/usr/bin/python3". On Windows: C:\Python312\python.exe

    deadline = time.time() + 5  # current timestamp for checking repeatedly within 5 seconds active wait.
    # time.sleep(5): not recommended here.that would be blind waiting
    while time.time() < deadline:  # "Keep checking until deadline"
        active_pid = _get_active_process_pid(warn_on_invalid=False)
        # "Check PID file (don't warn if missing)" → check if scheduler started

        if active_pid is not None: # explicitly checking for existence with None
            return active_pid

        exit_code = process.poll() # "Did the process crash?". method of subprocess
        if exit_code is not None:
            raise RuntimeError(f"Detached scheduler failed to start (exit {exit_code})")

        time.sleep(0.1)  # Wait 100ms repeatedly between checks → avoid CPU burn

    raise RuntimeError("Detached scheduler did not create a PID file in time")

def _read_interval_from_process(process: psutil.Process) -> int | None:
    # Scheduler background workers do not carry an interval argument in their process command line.
    # Keep the public adapter function for the shared mental map, but return None for this project.
    """Keep the shared adapter API shape; scheduler has no process interval, so return `None`."""
    del process # Usually unnecessary here.
    return None

def _stop_process(wait: bool = True) -> bool:
    """Stop the running scheduler process and optionally wait for a clean exit."""
    active_pid = _get_active_process_pid()
    if active_pid is None:
        logger.info("Scheduler is not running")
        return False

    try:
        process = psutil.Process(active_pid)
        # terminate() asks nicely (SIGTERM on Unix). kill() is the hard fallback.
        process.terminate()
    except psutil.NoSuchProcess:
        _remove_pid_file() # remove stale pid
        logger.info("Scheduler is not running")
        return False

    logger.info(f"Sent stop signal to scheduler process {active_pid}")

    if wait:
        try:
            # wait(timeout=10): block until exit, but only up to 10 seconds.
            process.wait(timeout=10)
            _remove_pid_file() 
            return True
        except psutil.TimeoutExpired:
            logger.warning(f"Scheduler process {active_pid} did not exit within timeout")
            process.kill() # Force kill (SIGKILL)
            process.wait(timeout=5) # # Wait up to 5s for it to die
            _remove_pid_file() # Clean up the PID file
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


def get_active_process_pid(*, warn_on_invalid: bool = True) -> int | None:
    """Public wrapper for resolving the currently running scheduler PID."""
    return _get_active_process_pid(warn_on_invalid=warn_on_invalid)


def spawn_detached_process(*, interval_secs: int | None = None) -> int:
    # Shared adapter signature across projects.
    # Scheduler does not need an interval, so we ignore it here on purpose.
    """Public wrapper for detached startup using the shared cross-project adapter signature."""
    del interval_secs
    return _spawn_detached_process()


def read_process_interval_seconds(process: psutil.Process) -> int | None:
    """Public wrapper for interval inspection; scheduler always returns `None` here."""
    return _read_interval_from_process(process)


def stop_process(wait: bool = True) -> bool:
    """Public wrapper for stopping the scheduler background process."""
    return _stop_process(wait=wait)
