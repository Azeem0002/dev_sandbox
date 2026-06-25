"""Runtime/environment adapter for autoclear.

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


APP_NAME = "autoclear"
APP_AUTHOR = "Al-Azeem"

# ============================================
# Runtime adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================

# Detect environment
def _get_platform_dirs() -> PlatformDirs:
    """Return the OS-specific per-user directories this app should treat as its home."""
    # `platformdirs` hides OS differences like:
    # Linux -> ~/.local/share/<app>, Windows -> AppData, macOS -> Library/Application Support
    return PlatformDirs(appname=APP_NAME, appauthor=APP_AUTHOR)


def _get_local_timezone():
    """Resolve the app's local timezone from explicit env override, then OS timezone, then UTC fallback."""
    tz_name = os.getenv("APP_LOCAL_TZ") or os.getenv("TZ")  # user overrides first, OS TZ second
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            logger.warning(f"Unknown timezone '{tz_name}', falling back to system local timezone")

    # astimezone().tzinfo asks Python for the OS-local timezone attached to "now".
    detected = datetime.now().astimezone().tzinfo  # Ask the OS "what timezone am I in right now?"
    if detected is not None:
        return detected

    return ZoneInfo("UTC")


# ============================================
# Project-specific extensions
# ============================================
def _get_worker_script_path() -> Path:
    """Return the worker entry script path used by detached process and service backends."""
    # One helper owns this path so process/service code does not duplicate worker entry knowledge.
    return Path(__file__).with_name("autoclear.py").resolve()
# Why "one helper": If the worker script name changes, you only update this ONE function, not everywhere it's referenced.



def _setup_environment() -> Path:
    """Prepare runtime-owned directories and return the concrete autoclear log file path."""
    dirs = _get_platform_dirs()
    log_dir = Path(dirs.user_log_dir)
    # Runtime setup is allowed to mutate the filesystem because "setup" is the responsibility name.
    log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    return log_dir / "autoclear.log"


# Logging

def _is_dev_env() -> bool:
    """Return whether runtime behavior should stay in development mode instead of production mode."""
    # Default to dev so local runs are noisy and easier to debug unless prod is explicit.
    return os.getenv("APP_ENV", "dev").strip().lower() != "prod"

def _setup_logger(log_file: Path) -> None:
    """Configure console and rotating file logging for the autoclear runtime."""
    logger.remove()
    if not _is_dev_env():
        # Prod: keep terminal logging quieter and simpler.
        logger.add(
            sys.stdout,
            level="INFO",
            enqueue=True,
        )
    else:
        # Dev: include module/function/line so debugging is faster.
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

    logger.add(
        log_file,
        # Rotating file log keeps history without growing forever.
        level="DEBUG",
        rotation="1 MB",
        retention="3 days",
        compression="zip",
        enqueue=True,
        backtrace=False,
        diagnose=False,
    )


# ============================================
# Public adapter API - stable reusable surface
# Responsibility-order adapters are grouped by the job they do, not by install/start/stop lifecycle.
# Read them as: prepare inputs -> call the outside system -> map results back to app-safe data.
# ============================================
def get_platform_dirs() -> PlatformDirs:
    """Public wrapper for resolving app-owned platform directories."""
    return _get_platform_dirs()


def get_local_timezone():
    """Public wrapper for local timezone resolution with env override support."""
    return _get_local_timezone()


def setup_environment() -> Path:
    """Public wrapper for preparing runtime directories and returning the autoclear log path."""
    return _setup_environment()

def is_dev_env() -> bool:
    """Public wrapper for dev/prod environment detection."""
    return _is_dev_env()

def setup_logger(log_file: Path) -> None:
    """Public wrapper for configuring autoclear logging sinks."""
    return _setup_logger(log_file)


def get_worker_script_path() -> Path:
    """Public wrapper for resolving the autoclear worker entry script path."""
    return _get_worker_script_path()
