"""Runtime/environment adapter for partner_match_8.

This module owns app directories, environment-mode detection, and logger setup.
Keep business rules out of this layer.
"""

import os
import sys
from pathlib import Path

from loguru import logger
from platformdirs import PlatformDirs


APP_NAME = "partner_match"
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
    # Default to dev so local runs are easier to debug unless production is explicit.
    return os.getenv("APP_ENV", "dev").strip().lower() != "prod"


def _setup_environment() -> Path:
    """Prepare runtime-owned directories and return the concrete partner_match log file path."""
    dirs = _get_platform_dirs()
    data_dir = Path(dirs.user_data_dir)
    log_dir = Path(dirs.user_log_dir)
    # Runtime setup is allowed to mutate the filesystem because "setup" is the responsibility name.
    data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    return log_dir / "partner_match.log"


def _setup_logger(file_log: Path) -> None:
    """Configure console and rotating file logging for the partner_match runtime."""
    logger.remove()

    if not _is_dev_env():
        # Prod: keep terminal logging quieter and simpler.
        logger.add(sink=sys.stderr, level="INFO", enqueue=False)
    else:
        # Dev console: keep prompts readable. Full DEBUG detail still goes to the file log below.
        logger.add(
            sink=sys.stderr,
            level="INFO",
            format="<cyan>{time:YYYY-MM-DD HH:mm:ss}</cyan> | "
            "{level: <8} | "
            "{module}.{function}:{line} | "
            "<level>{message}</level>",
            colorize=True,
            enqueue=False,
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
# ============================================
def get_platform_dirs() -> PlatformDirs:
    """Public wrapper for resolving app-owned platform directories."""
    return _get_platform_dirs()


def is_dev_env() -> bool:
    """Public wrapper for dev/prod environment detection."""
    return _is_dev_env()


def setup_environment() -> Path:
    """Public wrapper for preparing runtime directories and returning the partner_match log path."""
    return _setup_environment()


def setup_logger(file_log: Path) -> None:
    """Public wrapper for configuring partner_match logging sinks."""
    _setup_logger(file_log)
