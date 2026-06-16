    """Small lifecycle/status models shared by autoclear boundary and application code."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AutoclearStatus:
    """Application-facing snapshot of the autoclear backend state."""
    backend: str
    is_running: bool
    pid: int | None
    interval_seconds: int | None
    last_trigger: str | None
    detail: str | None
    pid_file: Path | None = None
