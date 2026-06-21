"""Tiny OS detection adapter.

This isolates platform branching behind one reusable function so the rest
of the codebase does not scatter `os.name` / `sys.platform` checks.
"""

import os
import sys

# ============================================
# Platform adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================
def _detect_platform_impl() -> str:
    """Normalize host platform names into the app's small platform vocabulary."""
    # Return a tiny app-owned vocabulary so higher layers branch on stable names,
    # not on every raw platform string Python exposes.
    # `os.name` is good for broad family detection.
    # `sys.platform` is better for distinguishing Linux vs macOS.
    if os.name == "nt":
        return "windows"

    if sys.platform.startswith("linux"):
        return "linux"

    if sys.platform == "darwin":
        return "mac"

    return "unknown"


# ============================================
# Public adapter API - stable reusable surface
# ============================================
def detect_platform() -> str:
    """Public wrapper for host platform normalization."""
    return _detect_platform_impl()
