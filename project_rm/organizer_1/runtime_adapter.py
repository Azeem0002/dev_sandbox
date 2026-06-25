"""Runtime/environment adapter for organizer.

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

try:
    from .models import APP_DIRS, BACKUP_DIR, LOG_DIR
except ImportError:
    from models import APP_DIRS, BACKUP_DIR, LOG_DIR


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
    # Organizer already centralizes path constants in models.py, so reuse that single object.
    return APP_DIRS


def _is_dev_env() -> bool:
    """Return whether runtime behavior should stay in development mode instead of production mode."""
    # Default to dev so local runs are noisy and easier to debug unless prod is explicit.
    return os.getenv("APP_ENV", "dev").strip().lower() != "prod"


def _get_local_timezone():
    """Resolve the app's local timezone from explicit env override, then OS timezone, then UTC fallback."""
    tz_name = os.getenv("APP_LOCAL_TZ") or os.getenv("TZ")
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            logger.warning(f"Unknown timezone '{tz_name}', falling back to system local timezone")

    # astimezone().tzinfo asks Python for the OS-local timezone attached to "now".
    detected = datetime.now().astimezone().tzinfo
    if detected is not None:
        return detected

    return ZoneInfo("UTC")


# REUSABLE: small cross-project pattern for preparing app-owned directories.
def _setup_environment() -> Path:
    """Create organizer-owned runtime directories and return the concrete organizer log file path."""
    # Setup owns side effects like creating app folders; getters should stay pure.
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR / "organizer.log"


# REUSABLE: dual logger setup pattern for CLI apps.
def _setup_logger(log_file: Path) -> None:
    """Configure console and file logging for organizer with different dev/prod verbosity."""
    logger.remove()
    if not _is_dev_env():
        logger.add(
            sink=sys.stderr,
            level="INFO",
            format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
            colorize=True,
            backtrace=True,
            catch=True,
        )
    else:
        logger.add(
            sink=sys.stderr,
            level="DEBUG",
            format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
            colorize=True,
            backtrace=True,
            catch=True,
        )
    logger.add(
        sink=str(log_file),
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {module}.{function}:{line} | {message}",
        rotation="10 MB",
        retention="30 days",
        compression="gz",
        serialize=True,
        enqueue=True,
        backtrace=True,
        catch=True,
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
    """Public wrapper for preparing organizer runtime directories and returning the log path."""
    return _setup_environment()


def setup_logger(log_file: Path) -> None:
    """Public wrapper for configuring organizer logging sinks."""
    _setup_logger(log_file)


# ============================================
# Backward-compatible aliases - old names
# ============================================
# Do not alias names that already exist as private implementations.
# Rebinding `_get_local_timezone = get_local_timezone` makes the public wrapper
# call itself forever, which causes RecursionError.
_setup_env = setup_environment
setup_runtime_environment = setup_environment
