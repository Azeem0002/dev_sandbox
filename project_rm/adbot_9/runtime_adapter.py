"""Runtime/environment adapter for adbot_9."""

import os
import sys
from pathlib import Path

from loguru import logger
from platformdirs import PlatformDirs


APP_NAME = "adbot"
APP_AUTHOR = "Al-Azeem"

# ============================================
# Runtime adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================
def _get_platform_dirs() -> PlatformDirs:
    """Return the OS-specific per-user directories this app should treat as its home."""
    # `platformdirs` prevents hardcoded Linux/Windows/macOS paths in the rest of the app.
    return PlatformDirs(APP_NAME, APP_AUTHOR)


def _is_dev_env() -> bool:
    """Return whether runtime behavior should stay in development mode."""
    return os.getenv("APP_ENV", "dev").strip().lower() != "prod"


def _setup_environment() -> Path:
    """Prepare runtime-owned directories and return the concrete log file path."""
    dirs = _get_platform_dirs()
    log_dir = Path(dirs.user_log_dir)
    # Runtime setup owns directory creation; getters should stay pure.
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "adbot.log"


def _setup_logger(file_log: Path) -> None:
    """Configure console and rotating file logging."""
    logger.remove()
    # Console logs are operator feedback; file logs are debugging history.
    logger.add(sink=sys.stderr, level="INFO", enqueue=False)
    logger.add(
        sink=file_log,
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {module}.{function}:{line} | {message}",
        rotation="1 MB",
        retention="3 days",
        compression="zip",
        enqueue=True,
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


def setup_environment() -> Path:
    """Public wrapper for preparing runtime directories and returning the log path."""
    return _setup_environment()


def setup_logger(file_log: Path) -> None:
    """Public wrapper for configuring logging sinks."""
    _setup_logger(file_log)
