"""Lifecycle/status models shared by scheduler boundary and application code."""

from dataclasses import dataclass
from pathlib import Path
from datetime import datetime


@dataclass(frozen=True)
class SchedulerStatus:
    """Application-facing snapshot of the scheduler daemon state."""
    is_running: bool
    pid: int | None
    process_status: str | None
    started_at: datetime | None
    pid_file: Path
    active_jobs: int
    paused_jobs: int

    @property
    def total_jobs(self) -> int: # Computed/Derived data, not stored as property method not field
        """Total jobs."""
        return self.active_jobs + self.paused_jobs
