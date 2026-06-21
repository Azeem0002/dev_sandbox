"""Standalone autoclear worker.

This is the executable worker process that actually clears the terminal.
Adapters may launch it directly in foreground, background, or via OS schedulers.
"""

import subprocess
import time
import os # python standard module for interacting with the operating system
import sys
from dataclasses import dataclass
from typing import Callable # Callable: Anything you can call like a function: something()

from loguru import logger
from tenacity import retry, stop_after_attempt, wait_fixed

try:
    from .lifecycle_models import AutoclearConfig
    from .runtime_adapter import (setup_environment, setup_logger)
except ImportError:
    from .lifecycle_models import AutoclearConfig
    from runtime_adapter import setup_environment, setup_logger





# =============================================================================
# RESPONSIBILITY (PURE)
# =============================================================================

def _get_clear_command() -> list[str]:
    """Return clear command."""
    return ["cmd", "/c", "cls"] if os.name == "nt" else ["clear"]
    # "/c": run command and exit
    
def _execute_command(command: list[str]) -> None:
    # subprocess.run() expects command as list of arguments, not a single string. ["command", "arg1", "arg2"]
    # List prevents command injection vulnerabilities
    """Execute command."""
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
    """Log before."""
    attempt = retry_state.attempt_number
    logger.info(f"Attempt {attempt}/{retry_state.retry_object.stop.max_attempt_number}")
    

def _log_after(retry_state):
    """Log after."""
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
    """Clear terminal."""
    command = _get_clear_command()
    operation = with_retry(config.max_retries, config.retry_delay)(_execute_command)
    operation(command)


def run_autoclear_once(config: AutoclearConfig) -> None:
    """Run autoclear once."""
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
    """Initialize the runtime environment for this module."""
    # Worker and controller share the same runtime adapter so log paths/settings do not drift.
    log_file = setup_environment()
    setup_logger(log_file)

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
        logger.info("Invalid time interval. (e.g. 1m, 5m, 2h)")
        sys.exit(1)
