from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SchedulerStatus:
    is_running: bool
    pid: int | None
    process_status: str | None
    started_at: str | None
    pid_file: Path
    active_jobs: int
    paused_jobs: int

    @property
    def total_jobs(self) -> int:
        return self.active_jobs + self.paused_jobs
