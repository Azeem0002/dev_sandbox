
import subprocess
import time
import os
from dataclasses import dataclass
from typing import Callable
from tenacity import retry, stop_after_attempt, wait_fixed


# =============================================================================
# DOMAIN
# =============================================================================

@dataclass(frozen=True)
class AutoclearConfig:
    interval: int = 600
    max_retries: int = 3
    retry_delay: float = 1.0


# =============================================================================
# RESPONSIBILITY (PURE)
# =============================================================================

def _get_clear_command() -> list[str]:
    return ["cmd", "/c", "cls"] if os.name == "nt" else ["clear"]

def _execute_command(command: list[str]) -> None:
    subprocess.run(command, check=True)

def _sleep(seconds: int) -> None:
    time.sleep(seconds)


# =============================================================================
# FEATURES (COMPOSABLE)
# =============================================================================

def with_retry(max_attempts: int, delay: float) -> Callable:
    def decorator(func: Callable) -> Callable:
        @retry(stop=stop_after_attempt(max_attempts), wait=wait_fixed(delay))
        def wrapped(*args, **kwargs):
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

    operation(command)

# =============================================================================
# PUBLIC FUNCTION (WORKER LOOP)
# =============================================================================
def run_autoclear(config: AutoclearConfig) -> None:
    """
    Robot loop.
    No lifecycle control here.
    External controller decides when this process dies.
    """
    while True:
        clear_terminal(config)
        _sleep(config.interval)