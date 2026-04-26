import os
import sys
from pathlib import Path

from loguru import logger
from platformdirs import PlatformDirs


APP_NAME = "scheduler"
APP_AUTHOR = "Al-Azeem"


def _get_platform_dirs() -> PlatformDirs:
    return PlatformDirs(APP_NAME, APP_AUTHOR)


def _setup_env() -> Path:
    log_dir = Path(_get_platform_dirs().user_log_dir)

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        logger.debug("Failed to create directory")
        raise PermissionError("Failed to create directory") from error

    return log_dir / "scheduler.log"


def _setup_logger(file_log: Path) -> None:
    env = os.getenv("APP_ENV", "dev")
    logger.remove()

    if env == "prod":
        logger.add(
            sink=sys.stdout,
            level="INFO",
        )
    else:
        logger.add(
            sink=sys.stdout,
            level="DEBUG",
            format="<cyan>{time:YYYY-MM-DD HH:mm:ss}</cyan> | "
            "{level: <8} | "
            "{module}.{function}:{line} | "
            "<level>{message}</level>",
            colorize=True,
            backtrace=True,
        )

    logger.add(
        sink=file_log,
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
