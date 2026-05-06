import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger
from platformdirs import PlatformDirs

try:
    from .models import APP_CONFIG, BACKUP_DIR, LOG_DIR
except ImportError:
    from models import APP_CONFIG, BACKUP_DIR, LOG_DIR


# ============================================
# Runtime adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================
def get_platform_dirs() -> PlatformDirs:
    """Return the per-user app directories chosen by `platformdirs`."""
    return PlatformDirs(APP_CONFIG.app_name, APP_CONFIG.app_author)


def is_dev_env() -> bool:
    """Treat anything except explicit `APP_ENV=prod` as development mode."""
    return os.getenv("APP_ENV", "dev").strip().lower() != "prod"


def get_local_timezone():
    """Resolve local timezone from env override -> OS timezone -> UTC fallback."""
    tz_name = os.getenv("APP_LOCAL_TZ") or os.getenv("TZ")
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            logger.warning(f"Unknown timezone '{tz_name}', falling back to system local timezone")

    detected = datetime.now().astimezone().tzinfo
    if detected is not None:
        return detected

    return ZoneInfo("UTC")


# REUSABLE: small cross-project pattern for preparing app-owned directories.
def setup_environment() -> Path:
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
    except PermissionError as error:
        logger.error(
            f"Cannot create directories. Check write permissions for: {BACKUP_DIR.parent} and {LOG_DIR}"
        )
        raise PermissionError(f"Directory creation failed: {error}") from error
    return LOG_DIR / "organizer.log"


# REUSABLE: dual logger setup pattern for CLI apps.
def setup_logger(log_file: Path) -> None:
    logger.remove()
    if not is_dev_env():
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
# Backward-compatible aliases - old names
# ============================================
setup_runtime_environment = setup_environment
