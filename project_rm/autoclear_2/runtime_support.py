import os
import sys
from pathlib import Path

from loguru import logger
from platformdirs import PlatformDirs


APP_NAME = "autoclear"
APP_AUTHOR = "Al-Azeem"
SYSTEMD_SERVICE_NAME = "autoclear.service"
SYSTEMD_TIMER_NAME = "autoclear.timer"


def _get_platform_dirs() -> PlatformDirs:
    return PlatformDirs(appname=APP_NAME, appauthor=APP_AUTHOR)


def _get_worker_script_path() -> Path:
    return Path(__file__).with_name("autoclear.py").resolve()


def _setup_env() -> Path:
    dirs = _get_platform_dirs()
    log_dir = Path(dirs.user_log_dir)

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        logger.debug("Failed to create directory")
        raise PermissionError("Failed to create directory") from error

    return log_dir / "autoclear.log"


def _setup_logger(log_file: Path) -> None:
    env = os.getenv("APP_ENV", "dev")

    logger.remove()
    if env == "prod":
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
