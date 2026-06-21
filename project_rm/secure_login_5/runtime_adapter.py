"""Runtime/environment adapter for secure_login_5."""

import os
import sys
from pathlib import Path

from loguru import logger
from platformdirs import PlatformDirs


APP_NAME = "secure_login"
APP_AUTHOR = "Al-Azeem"

# ============================================
# Runtime adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================
def _get_platform_dirs() -> PlatformDirs:
    """Return the OS-specific per-user directories this app should treat as its home."""
    # `platformdirs` gives one app-owned location per OS/user.
    # The rest of the app should not hardcode ~/.local, AppData, or macOS Library paths.
    return PlatformDirs(APP_NAME, APP_AUTHOR)


def _is_dev_env() -> bool:
    """Return whether runtime behavior should stay in development mode."""
    # Default to dev so local runs are easier to debug unless production is explicit.
    return os.getenv("APP_ENV", "dev").strip().lower() != "prod"


def _setup_environment() -> Path:
    """Prepare runtime-owned directories and return the concrete log file path."""
    dirs = _get_platform_dirs()
    log_dir = Path(dirs.user_log_dir)
    # Runtime setup is allowed to mutate the filesystem because "setup" is the responsibility name.
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "secure_login.log"


def _setup_logger(file_log: Path) -> None:
    """Configure console and rotating file logging."""
    logger.remove()
    # Console logging is for operators/devs; file logging is for later debugging.
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
