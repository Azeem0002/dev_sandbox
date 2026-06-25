"""Runtime/environment adapter for scheduler.

This module owns app directories, environment-mode detection, timezone lookup,
and logger setup. Keep business rules out of this layer.
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger
from platformdirs import PlatformDirs


APP_NAME = "scheduler"
APP_AUTHOR = "Al-Azeem"

# ============================================
# Runtime adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================
def _get_platform_dirs() -> PlatformDirs:
    """Return the OS-specific per-user directories this app should treat as its home."""
    # `platformdirs` hides OS differences like:
    # Linux -> ~/.local/share/<app>, Windows -> AppData, macOS -> Library/Application Support
    return PlatformDirs(APP_NAME, APP_AUTHOR)


def _is_dev_env() -> bool:
    """Return whether runtime behavior should stay in development mode instead of production mode."""
    # Default to dev so local runs are noisy and easier to debug unless prod is explicit.
    return os.getenv("APP_ENV", "dev").strip().lower() != "prod"


def _get_local_timezone():
    """Resolve the app's local timezone from explicit env override, then OS timezone, then UTC fallback."""
    tz_name = os.getenv("APP_LOCAL_TZ") or os.getenv("TZ") # env override first, system TZ second
    if tz_name:
        try:
            return ZoneInfo(tz_name)  # → convert string → timezone object
        except ZoneInfoNotFoundError:
            logger.warning(f"Unknown timezone '{tz_name}', falling back to system local timezone")

    # astimezone().tzinfo asks Python for the OS-local timezone attached to "now".
    detected = datetime.now().astimezone().tzinfo # Ask the OS "what timezone am I in right now?"
    if detected is not None:
        return detected

    return ZoneInfo("UTC")


def _setup_environment() -> Path:
    """Prepare runtime-owned directories and return the concrete scheduler log file path."""
    dirs = _get_platform_dirs()
    log_dir = Path(dirs.user_log_dir)
    # Runtime setup is allowed to mutate the filesystem because "setup" is the responsibility name.
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "scheduler.log"


def _setup_logger(file_log: Path) -> None:
    """Configure console and rotating file logging for the scheduler runtime."""
    logger.remove()

    if not _is_dev_env():
        # Prod: keep terminal logging quieter and simpler.
        logger.add(
            sink=sys.stdout,
            level="INFO",
        )
    else:
        # Dev: include module/function/line so debugging is faster.
        logger.add(
            sink=sys.stdout,
            level="DEBUG",
            format="<cyan>{time:YYYY-MM-DD HH:mm:ss}</cyan> | "
            "{level: <8} | "
            "{module}.{function}:{line} | "
            "<level>{message}</level>",
            colorize=True,
            enqueue=True,
            backtrace=True,
        )

    logger.add(
        sink=file_log,
        # Rotating file log keeps history without growing forever.
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {module}.{function}:{line} | {message}",
        rotation="1 MB",
        retention="3 days",
        compression="zip",
        enqueue=True,
        serialize=False,
        backtrace=False,
        diagnose=False,
        catch=False,
    )


# ============================================
# Public adapter API - stable reusable surface
# Responsibility-order adapters are grouped by the job they do, not by install/start/stop lifecycle.
# Read them as: prepare inputs -> call the outside system -> map results back to app-safe data.
# ============================================
def get_platform_dirs() -> PlatformDirs:
    """Public wrapper for resolving app-owned platform directories."""
    return _get_platform_dirs()


def is_dev_env() -> bool:
    """Public wrapper for dev/prod environment detection."""
    return _is_dev_env()


def get_local_timezone():
    """Public wrapper for local timezone resolution with env override support."""
    return _get_local_timezone()


def setup_environment() -> Path:
    """Public wrapper for preparing runtime directories and returning the scheduler log path."""
    return _setup_environment()


def setup_logger(file_log: Path) -> None:
    """Public wrapper for configuring scheduler logging sinks."""
    _setup_logger(file_log)


# ============================================
# Backward-compatible aliases - old names
# ============================================
# Do not alias names that already exist as private implementations.
# Rebinding `_get_local_timezone = get_local_timezone` makes the public wrapper
# call itself forever, which causes RecursionError.
_setup_env = setup_environment
