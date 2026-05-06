import os
import sys

# ============================================
# Platform adapter - reusable mental map
# ============================================

# ============================================
# Public adapter API - stable reusable surface
# ============================================

def detect_platform() -> str:
    if os.name == "nt":
        return "windows"

    if sys.platform.startswith("linux"):
        return "linux"

    if sys.platform == "darwin":
        return "mac"

    return "unknown"


_detect_platform = detect_platform
