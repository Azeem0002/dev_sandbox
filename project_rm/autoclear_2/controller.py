#! usr/bin/env python3

import tempfile
import subprocess
import sys
import time
import os
from pathlib import Path

import psutil
import typer
import pytimeparse
from loguru import logger
from platformdirs import PlatformDirs


# =======================================================
#   SETUP ENVIRONMENT & LOGGING CONFIGURATION
# =======================================================

APP_NAME = "autoclear"
APP_AUTHOR="Al-Azeem"

def _setup_env()-> Path:

    dirs = PlatformDirs(appname=APP_NAME, appauthor=APP_AUTHOR)

    LOG_DIR = Path(dirs.user_log_dir)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.debug(f" Failed to create directory")
        raise PermissionError(f"Failed to create directory") from e

    file_log = LOG_DIR / "autoclear.log"
    return file_log

def _setup_logger(log_file: Path)-> None:

    ENV = os.getenv("APP_ENV", "dev")

    logger.remove()
     # --- To STDOUT (terminal) ---
    if ENV == "prod":
        logger.add(
            sys.stdout,
            level="INFO",
            enqueue=True,
        )
    else:
        logger.add(
            sys.stdout,
            level="DEBUG",
            format="<yellow>{time:YYYY-MM-DD HH:mm:ss}</yellow> | "
                   "<level>{level: <8}</level> | "
                   "<cyan>{module}.{function}:{line}</cyan> | "
                   "<level>{message}</level>",
            colorize=True,
            enqueue=True,
            backtrace=True,
        )

    # --- To FILE (always consistent) ---
    logger.add(
        log_file,
        level="DEBUG",
        rotation="1 MB",
        retention="3 days",
        compression="gz",
        enqueue=True,
        backtrace=False,
        diagnose=False,
    )


# =======================================================
#    RESPONSIBILITIES
# =======================================================

# STATUS

def _get_pid_file_path() -> Path:
    """Returns path to PID file with proper isolation"""
    temp_dir = Path(tempfile.gettempdir()) / APP_NAME

    # we create with restrictive permissions (only owner can access)
    temp_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    return temp_dir / "autoclear.pid"

def _read_pid_file(pid_file: Path)-> int | None:  # Read safely
    
    try:
        content = pid_file.read_text().strip()
        return int(content)
    
    except(FileNotFoundError, ValueError, OSError):
        return None
    

def _is_process_running(pid: int)-> bool:  # OS check
    """Check if process with given PID exists."""
    return psutil.pid_exists(pid)

    
def _is_our_process(pid: int)-> bool:  # security
    """Verify process is actually autoclear.
    
    Without this:

    PID file → 1234
    Process 1234 → nginx
    You kill nginx
    """

    # check if process exists
    # _is_process_running(pid)
    
    try:
        proc = psutil.Process(pid)

        # Check if it's our robot (python running autoclear.py)
        cmdline = ", ".join(proc.cmdline())
        
        return "autoclear.py" in cmdline
    except OSError:
        return False

    
# STOP

def _terminate_pid(pid: int)-> None:

    proc = psutil.Process(pid) # get running Process
    proc.terminate() # graceful termination

    try:
        proc.wait(timeout= 3)

    except psutil.TimeoutExpired:
        proc.kill() # Force kill

def _delete_pid_file(pid_file: Path)-> None:

    try:
        pid_file.unlink(missing_ok=True)
    except OSError as e:
        raise PermissionError(f"failed to delete pid file: {pid_file}") from e

# START

def _write_pid_to_file(pid_file: Path, pid: int)-> None:
    """Write PID to file. Raises RuntimeError on failure."""
    logger.debug(f"Writing PID {pid} to {pid_file}")
    
    try:
        pid_file.write_text(str(pid))
    except OSError as e:
        logger.debug(f"file does not have write permission: {e}")
        raise RuntimeError(f"Failed to write to pid file: {pid_file}") from e
   
def _spawn_process(interval: int)-> subprocess.Popen:

    controller_dir = Path(__file__).parent / "autoclear.py"
    # Path(__file__).parent / "autoclear.py". Builds absolute path: python .venv

    command = [sys.executable, str(controller_dir), str(interval)]
    # sys.executable: full path to current python interpreter. /home/az/dev_sandbox/.venv/bin/python3
    
    # subprocess expects list[str]
    return subprocess.Popen( 
        command,
        stdout= None, # Inherits from parent (prints to terminal)
        stderr= None, # Inherits from parent (show errors)
        stdin= None,  # Inherits from parent (can receive inputs)
        start_new_session= True,  # Detach from controller
    )

def _parse_interval(value: str)-> int:
    """Typer callback for interval parsing."""

    if value.isdigit(): # isdigit(): works only on str not int
        # Checks if all characters in a string are numeric digits (0–9).
        return int(value)
    
    seconds = pytimeparse.parse(value) # convert value to pytimeparse
    if seconds is None:
        raise ValueError(f"Invalid time format: {value}")
    
    if seconds <= 0:
        raise ValueError(f"Interval must be > 0")
    
    if seconds > 172800: # Security: 2days cap
        raise ValueError(f"Interval too large. (max 2 days)")
    return int(seconds)



# =======================================================
#    APPLICATION LAYER
# =======================================================
    
def status_autoclear()-> str: # orchestration
    """
    Check if autoclear robot is running.
    
    Returns:
        "RUNNING (PID: 1234)" if running
        "STOPPED" if not running
    """

    # Step 1: Check if PID file exists
    pid_file = _get_pid_file_path()
    if not pid_file.is_file():
        # logger.info("Autoclear not running")
        return "STOPPED: Autoclear not running"
    
    # Step 2: Read PID from file
    pid = _read_pid_file(pid_file)
    if pid is None:
        logger.warning("Stale PID file detected")
        return "STALE"

    # Step 3: Verify process is running
    running = _is_process_running(pid)
    if not running:
        return "STALE (stale PID file)"
    
    # Step 4: Verify process it's our process
    our_process = _is_our_process(pid)
    if not our_process:
        logger.error("PID belongs to another process")
        return "STOPPED (unknown process)"
    
    return f"RUNNING: (PID: {pid})"

def stop_autoclear()-> str | bool:

    pid_file = _get_pid_file_path()
    pid = _read_pid_file(pid_file)

    
    if pid is None: # use "is None" for return type int
        return "Already stopped"
    
    # Cleanup stale
    if not _is_process_running(pid): # use "if not" for return type bool. returns only True or False
        try:
            _delete_pid_file(pid_file)
            logger.info(f"Cleaned up stale pid file: {pid_file}")
            return True
        except RuntimeError:
            logger.error(f"Failed to clean stale pid file: {pid_file}.")
            return False
        
    
    if not _is_our_process(pid):
        # better to not kill than kill wrong process. prevents hijacking
        return "Not our process, refusing to kill"
    
    try:
        _terminate_pid(pid)
        _delete_pid_file(pid_file)
        return "Autoclear stopped"
    
    except RuntimeError as e:
        logger.error(f"Failed to stop {str(e)}")
        return f"Failed to stop "

def start_autoclear(interval: str)-> bool:
    """
    Start autoclear robot.
    
    Args:
        interval: Human-readable interval like "2h 30m" or "600"
    
    Returns:
        True if started successfully
        False if already running
    """
    interval_secs = _parse_interval(interval)

    # check if already running
    pid_file = _get_pid_file_path()
    existing_pid = _read_pid_file(pid_file)

    if existing_pid is not None:
        if _is_process_running(existing_pid) and _is_our_process(existing_pid):
            logger.warning(f"Autoclear already running: {existing_pid}")
            return False
        
        # Only clean if stale
        _delete_pid_file(pid_file)
        logger.debug(f"Cleaned stale PID: {existing_pid}")
        
    

    # lunch process
    process = _spawn_process(interval_secs)

    # save pid to file
    _write_pid_to_file(pid_file, process.pid)
    
    time.sleep(0.3)
    # log success
    logger.info(f"Autoclear is starting with interval: {interval_secs}s: (PID={process.pid})")
    return True
    
def restart_autoclear(interval: str) -> bool:
    """
    Restart autoclear robot.
    
    Args:
        interval: New interval (optional, uses existing if not provided)
    
    Returns:
        True if restarted successfully
        False if wasn't running or restart failed
    """
    logger.info(f"Restarting autoclear with interval: {interval}")

    # Stop first
    try:
        stop_autoclear()

    except RuntimeError:
        pass # Ignore if already stopped
    # start
    return start_autoclear(interval)




# =======================================================
#    CLI LAYER
# =======================================================
app = typer.Typer()

@app.callback() # global setup. run once 
def init():
    LOG_FILE = _setup_env()
    _setup_logger(LOG_FILE)
    

@app.command()
def status():
    result = status_autoclear()
    typer.echo(result)


@app.command()
def stop():
    result = stop_autoclear()
    typer.echo(result)

@app.command()
def start(interval: str = typer.Option("1h", "-i", help="Interval e.g. 10s, 5m, 2h")):
    """
    Examples:
        autoclear start 600
        autoclear start 2h 30m
        autoclear start 30m
    """
    result = start_autoclear(interval)
    
    if result:
        time.sleep(1)
        typer.echo("Autoclear started")

@app.command()
def restart(seconds: str= typer.Option("60m", "-i", help= "New interval (e.g., 600, 2h 30m)")):

    result = restart_autoclear(seconds)
    time.sleep(1)
    if result:
        interval = _parse_interval(seconds)
        typer.echo(f"Autoclear restarted successfully with {interval} ")
        return True
    else:
        typer.BadParameter(f"Failed to restart autoclear: {result}")
        raise typer.Exit(code=1)

if __name__=="__main__":

    app()