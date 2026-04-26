from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AutoclearStatus:
    backend: str
    is_running: bool
    pid: int | None
    interval_seconds: int | None
    last_trigger: str | None
    detail: str | None
    pid_file: Path | None = None
