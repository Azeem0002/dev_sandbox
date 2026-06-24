"""Validation/parsing helpers for autoclear boundary input.

This module owns user-input cleanup. Application code should receive already
meaningful values, not raw terminal strings that still need parsing.
"""

import pytimeparse


# ============================================
# Validation - reusable mental map
# ============================================
MIN_DURATION_SECONDS = 60


def parse_duration_seconds(value: int | str, *, field_name: str = "duration") -> int:
    """Parse flexible time input like `3d`, `1m`, `1h 30m`, or plain seconds."""
    if isinstance(value, int): # type checking
        seconds = value # Already a number, use directly
    elif isinstance(value, str): # str input validation
        cleaned = value.strip() # Remove whitespace
        if not cleaned: # reject empty
            raise ValueError(f"{field_name} cannot be empty") 
        if cleaned.isdigit(): # is this string integers
            seconds = int(cleaned) # Plain number string like "3600" to be converted to integer
        else:
            parsed = pytimeparse.parse(cleaned) # Parse "1h 30m" → 5400
            if parsed is None:
                raise ValueError(f"Invalid {field_name}: {value}")
            seconds = int(parsed)
    else:
        raise ValueError(f"{field_name} must be a number or time expression")

    if seconds < MIN_DURATION_SECONDS:
        raise ValueError(f"{field_name} must be at least 1 minute")
    return seconds


def parse_interval(value: int | str) -> int:
    """Convert flexible user input like `1m`, `5m`, or `3600` into bounded seconds."""
    seconds = parse_duration_seconds(value, field_name="interval") # Reuse parsing logic
    if seconds > 172800:
        raise ValueError("Interval too large. (max 2 days)")
    return seconds


def format_duration_seconds(seconds: int | None) -> str:
    """Format seconds as machine value plus a small human-friendly label."""
    if seconds is None:
        return "unknown"
    if seconds % 86400 == 0:
        label = f"{seconds // 86400}d"
    elif seconds % 3600 == 0:
        label = f"{seconds // 3600}h"
    elif seconds % 60 == 0:
        label = f"{seconds // 60}m"
    else:
        label = f"{seconds}s"
    return f"{seconds}s ({label})"
