import subprocess
import sys
import time
from pathlib import Path

import psutil
from platformdirs import PlatformDirs
from loguru import logger

APP_NAME="scheduler"
APP_AUTHOR="Al-Azeem"

def _get_platform_dirs()-> PlatformDirs:
    return PlatformDirs(APP_NAME, APP_AUTHOR)

def _get_pid_file_path()-> Path:
    data_dir = Path(_get_platform_dirs().user_data_dir)
    try:
        data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        return data_dir / "scheduler.pid"
    except OSError as e:
        raise PermissionError("Failed to create directory") from e
