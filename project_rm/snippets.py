from platformdirs import PlatformDirs

APP_NAME="scheduler"
APP_AUTHOR="Al-Azeem"

def _get_platform_dir()-> PlatformDirs:
    return PlatformDirs(APP_NAME, APP_AUTHOR)

def _