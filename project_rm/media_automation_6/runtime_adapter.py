"""Runtime/environment adapter for media_automation_6."""

import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger
from platformdirs import PlatformDirs


APP_NAME = "media_automation"
APP_AUTHOR = "Al-Azeem"

# ============================================
# Runtime adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================
def _get_platform_dirs() -> PlatformDirs:
    """Return the OS-specific per-user directories this app should treat as its home."""
    # `platformdirs` hides OS differences like Linux ~/.local/share, Windows AppData, macOS Library.
    return PlatformDirs(APP_NAME, APP_AUTHOR)


def _is_dev_env() -> bool:
    """Return whether runtime behavior should stay in development mode instead of production mode."""
    # Default to dev so local runs are easier to debug unless production is explicit.
    return os.getenv("APP_ENV", "dev").strip().lower() != "prod"


def _get_local_timezone():
    """Resolve app timezone from env override, then OS timezone, then UTC fallback."""
    tz_name = os.getenv("APP_LOCAL_TZ") or os.getenv("TZ")
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            logger.warning(f"Unknown timezone '{tz_name}', falling back to system local timezone")
    detected = datetime.now().astimezone().tzinfo
    return detected or ZoneInfo("UTC")


def _setup_environment() -> Path:
    """Prepare runtime-owned directories and return the concrete log file path."""
    dirs = _get_platform_dirs()
    log_dir = Path(dirs.user_log_dir)
    # Runtime setup is allowed to mutate the filesystem because "setup" is the responsibility name.
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "media_automation.log"


def _setup_logger(file_log: Path) -> None:
    """Configure console and rotating file logging."""
    logger.remove()
    # Console logging gives immediate feedback; file logging preserves debugging history.
    logger.add(sink=sys.stderr, level="INFO", enqueue=False)
    logger.add(
        sink=file_log,
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {module}.{function}:{line} | {message}",
        rotation="1 MB",
        retention="3 days",
        compression="zip",
        enqueue=True,
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
    """Public wrapper for preparing runtime directories and returning the log path."""
    return _setup_environment()


def setup_logger(file_log: Path) -> None:
    """Public wrapper for configuring logging sinks."""
    _setup_logger(file_log)
