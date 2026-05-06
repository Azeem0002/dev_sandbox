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

def get_platform_dirs() -> PlatformDirs:
    """Return the per-user app directories chosen by `platformdirs`."""
    return PlatformDirs(appname=APP_NAME, appauthor=APP_AUTHOR)


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


# ============================================
# Project-specific extensions
# ============================================
def get_worker_script_path() -> Path:
    """Return the standalone worker script launched by process/service backends."""
    return Path(__file__).with_name("autoclear.py").resolve()


def setup_environment() -> Path:
    """Create the app log directory and return the concrete log file path."""
    dirs = get_platform_dirs()
    log_dir = Path(dirs.user_log_dir)

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        logger.debug("Failed to create directory")
        raise PermissionError("Failed to create directory") from error

    return log_dir / "autoclear.log"


def setup_logger(log_file: Path) -> None:
    """Configure stdout logging plus rotating file logging for this CLI app."""
    logger.remove()
    if not is_dev_env():
        logger.add(
            sys.stdout,
            level="INFO",
            enqueue=True,
        )
    else:
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
        level="DEBUG",
        rotation="1 MB",
        retention="3 days",
        compression="zip",
        enqueue=True,
        backtrace=False,
        diagnose=False,
    )


# ============================================
# Backward-compatible aliases - old names
# ============================================
_get_platform_dirs = get_platform_dirs
_is_dev_env = is_dev_env
_get_local_timezone = get_local_timezone
_get_worker_script_path = get_worker_script_path
_setup_env = setup_environment
_setup_logger = setup_logger
