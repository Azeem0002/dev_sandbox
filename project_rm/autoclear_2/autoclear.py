import subprocess
import time
import os # python standard module for interacting with the operating system
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Callable # Callable: Anything you can call like a function: something()

from platformdirs import PlatformDirs
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_fixed


# =============================================================================
# DOMAIN
# =============================================================================

def _setup_env()->Path:
    """cross platform path for logs"""

    APP_NAME= "autoclear"
    APP_AUTHOR= "Al-Azeem" # appauthor mainly matters on windows

    dirs = PlatformDirs(appname=APP_NAME, appauthor=APP_AUTHOR)
    
    LOG_DIR= Path(dirs.user_log_dir)

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.debug(f"Failed to create directory")
        raise PermissionError(f"Failed to create directory") from e

    log_file= LOG_DIR / "autoclear.log" 
    return log_file


def _setup_logger(log_file: Path)-> None:
    
    logger.remove() # remove default settings/ink

    ENV = os.getenv("APP_ENV", "dev") # os.getenv(key, value)
    # "APP_ENV": The key for ENV. can be an string
    # "dev" fallback value. default environment is determined by the fallback

    if ENV == "prod":
        # Production environment: stdout only
        logger.add(
        sink = sys.stdout,
        level= "INFO",
        enqueue= True,
        )

    # Development environment: stdout + file
    else:

        logger.add(
        sink = sys.stdout,
        level= "DEBUG",
        enqueue= True,
        backtrace=True,
        )

        logger.add(
            sink= log_file,
            level = "DEBUG",
            rotation= "2 MB",
            retention= "3 days", # or 3 files
            compression= "gz",
            serialize= True,
            enqueue= True,
            backtrace=True,
            catch=True,
            )


# ==========================
# CONFIGURATIONS
# ==========================
@dataclass(frozen=True)
class AutoclearConfig:
    interval: int = 3600 # 1h
    max_retries: int = 3
    retry_delay: float = 1.0


# =============================================================================
# RESPONSIBILITY (PURE)
# =============================================================================

def _get_clear_command() -> list[str]:
    return ["cmd", "/c", "cls"] if os.name == "nt" else ["clear"]
    # "/c": run command and exit
    
def _execute_command(command: list[str]) -> None:
    # subprocess.run() expects command as list of arguments, not a single string. ["command", "arg1", "arg2"]
    # List prevents command injection vulnerabilities
    try:
        subprocess.run(command, timeout=5, check=True)
        # logger.info("Terminal cleared")
    # check=True: if command fails → silently ignore CalledProcessError
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Clear failed: {command}") from e
        # RuntimeError: for hiding low level details for orchestrations
        # Reraise better error message- Optional


# =============================================================================
# FEATURES (COMPOSABLE)
# =============================================================================
def _log_before(retry_state): # Counting
    attempt = retry_state.attempt_number
    logger.info(f"Attempt {attempt}/{retry_state.retry_object.stop.max_attempt_number}")
    

def _log_after(retry_state):
    if retry_state.outcome.failed:
        logger.warning(f"Attempt failed: {retry_state.outcome.exception()}")
    else:
        logger.info("Attempt succeeded")

def with_retry(max_attempts: int, delay: float) -> Callable: # Calls decorator
    """
    Function that returns a decorator for retry functionality.
    Handles temporary glitches. transient error.
    """
    def decorator(func: Callable) -> Callable: # Callable: Anything you can call like wrapped() function
        """
        Decorator that wraps any function with retry logic.
        func: The original function to retry (e.g., _execute_command)
        """
        @retry(stop=stop_after_attempt(max_attempts), 
               wait=wait_fixed(delay),
               before= _log_before,  # logs for every failed retry
               after= _log_after, # logs & throw real error after max failed or succeeded retry attempts
               reraise=True) # raises last error after max attempts
        def wrapped(*args, **kwargs): # generic wrapper. accepts ANY function signature. executes original function
            """Wrapped function that will be replaced with original function: _execute_command """
            return func(*args, **kwargs)
        return wrapped
    return decorator


# =============================================================================
# PUBLIC FUNCTION (LEVEL 1 ORCHESTRATION)
# =============================================================================
def clear_terminal(config: AutoclearConfig) -> None:
    command = _get_clear_command()
    operation = with_retry(config.max_retries, config.retry_delay)(_execute_command)
    operation(command)


def run_autoclear_once(config: AutoclearConfig) -> None:
    clear_terminal(config)
    logger.success("Terminal cleared")

# =============================================================================
# PUBLIC FUNCTION (WORKER LOOP). main() workflow
# =============================================================================
def run_autoclear(config: AutoclearConfig) -> None:
    """
    Robot loop.
    No lifecycle control here.
    External controller decides when this process dies.
    """
        
    while True:
        try:
            run_autoclear_once(config)

        except RuntimeError: # Loop resilience → Handles permanent failures without crashing
            time.sleep(1) # throttle failures
        time.sleep(config.interval)

   
def init():
    LOG_FILE = _setup_env()
    _setup_logger(LOG_FILE)

if __name__ == "__main__":
    init()
    logger.info(f"Received interval: {sys.argv}")
    if "--once" in sys.argv:
        run_autoclear_once(AutoclearConfig())
        sys.exit(0)
    try:
        interval = int(sys.argv[1]) if len(sys.argv) > 1 else 3600 # 3600 is 1h 
        config = AutoclearConfig(interval)
        run_autoclear(config) # expects AutoclearConfig
    except ValueError:
        logger.info("Invalid time interval. (e.g. 10s, 5, 2h)")
        sys.exit(1)
