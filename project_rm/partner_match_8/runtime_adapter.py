"""Runtime/environment adapter for partner_match_8."""

from pathlib import Path

from loguru import logger
from platformdirs import PlatformDirs


# ============================================
# Runtime adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================
def _get_platform_dirs() -> PlatformDirs:
    """Return platform-owned directories for this app."""
    return PlatformDirs("partner_match", "Al-Azeem")


def _is_dev_env() -> bool:
    """Return whether the app should expose development diagnostics."""
    import os
    return os.getenv("APP_ENV", "dev").casefold() == "dev"


def _setup_environment() -> Path:
    """Create runtime directories and return log file path."""
    dirs = _get_platform_dirs()
    data_dir = Path(dirs.user_data_dir)
    log_dir = Path(dirs.user_log_dir)
    data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    return log_dir / "partner_match.log"


def _setup_logger(file_log: Path) -> None:
    """Configure file logging."""
    logger.remove()
    logger.add(file_log, rotation="1 MB", retention="3 days", level="DEBUG" if _is_dev_env() else "INFO")


# ============================================
# Public adapter API - stable reusable surface
# ============================================
def get_platform_dirs() -> PlatformDirs:
    """Public wrapper for platform dirs."""
    return _get_platform_dirs()


def is_dev_env() -> bool:
    """Public wrapper for environment mode."""
    return _is_dev_env()


def setup_environment() -> Path:
    """Public wrapper for runtime setup."""
    return _setup_environment()


def setup_logger(file_log: Path) -> None:
    """Public wrapper for logger setup."""
    _setup_logger(file_log)
