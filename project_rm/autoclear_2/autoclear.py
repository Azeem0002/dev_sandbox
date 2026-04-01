"""
with_retry()

clear_terminal()
    with_retry()
    _get_clear_command()
    _execute_command()
    

auto_run()
    loop
    clear_terminal
    _sleep

"""


import subprocess
import time
import os
import sys
from pathlib import Path
from loguru import logger
from dataclasses import dataclass
from typing import Callable # Callable: Anything you can call like a function: something()
from tenacity import retry, stop_after_attempt, wait_fixed


# =============================================================================
# DOMAIN
# =============================================================================

LOG_DIR  = Path.home()/ ".autoclear"/ "autoclear.log"

def setup_logging()-> None:
    file_log = "DEBUG"
    user_log = "INFO"

    logger.remove()
    logger.add(
        sink = sys.stderr,
        level= user_log,
        format= "{} |{}| {}",
        
    )

    logger.add(
        sink= LOG_DIR,
        level = file_log,
        rotation= "10 MB",
        retention= "7 days",
        compression= "gz",
        serialize= True,
        enqueue= True,
        # traceback=True,
    )


@dataclass(frozen=True)
class AutoclearConfig:
    interval: int = 3600
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
    # check=True: if command fails → raise CalledProcessError, if not → silently ignore failure ❌
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Clear failed: {command}") from e
        # Reraise better error message- Optional

def _sleep(seconds: int) -> None:
    time.sleep(seconds)


# =============================================================================
# FEATURES (COMPOSABLE)
# =============================================================================
def log_before(retry_state):
    attempt = retry_state.attempt_number
    logger.info(f"Attempt {attempt}/{retry_state.retry_object.stop.max_attempt_number}")
    

def log_after(retry_state):
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
               before= log_before,  # logs for every failed retry
               after= log_after, # logs & throw real error after max failed or succeeded retry attempts
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

    operation = with_retry(config.max_retries, config.retry_delay)(  
        _execute_command  
    )  
    if not operation:
        logger.error("Too many retires")
        
    operation(command)

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
            clear_terminal(config)
        except RuntimeError: # Loop resilience → Handles permanent failures without crashing
            logger.success("Terminal cleared")
            time.sleep(1) # throttle failures
        _sleep(config.interval)
        
        

if __name__ == "__main__":

    logger.info(f"Received interval: {sys.argv}")
    try:
        interval = int(sys.argv[1]) if len(sys.argv) > 1 else 3600 # 3600 is 1h 
        config = AutoclearConfig(interval)
        run_autoclear(config) # expects AutoclearConfig
    except ValueError:
        logger.info("Invalid time interval. (e.g. 10s, 5, 2h)")
        sys.exit(1)

    """
    sys.argv	        List of command-line arguments
    sys.argv[0]    	    First argument:Script name (e.g., autoclear.py)
    sys.argv[1]	        Second argument after script name which is the interval
    len(sys.argv) > 1	Check if argument was provided and greater than one argument
    int(sys.argv[1])	Convert argument to integer
    else 3600	Default value if no argument
    """