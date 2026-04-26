from datetime import datetime
from pathlib import Path
from typing import Callable
import sys

import psutil

try:
    from .lifecycle_models import SchedulerStatus
    from .process_adapter import _get_active_scheduler_pid, _get_pid_file_path, _spawn_detached_scheduler, stop_scheduler_process
except ImportError:
    from lifecycle_models import SchedulerStatus
    from process_adapter import _get_active_scheduler_pid, _get_pid_file_path, _spawn_detached_scheduler, stop_scheduler_process


def _build_scheduler_stopped_status(
    counts: dict[str, int],
    pid_file: Path,
) -> SchedulerStatus:
    return SchedulerStatus(
        is_running=False,
        pid=None,
        process_status=None,
        started_at=None,
        pid_file=pid_file,
        active_jobs=counts.get("active", 0),
        paused_jobs=counts.get("paused", 0),
    )


def _build_scheduler_running_status(
    pid: int,
    counts: dict[str, int],
    pid_file: Path,
    local_timezone,
) -> SchedulerStatus:
    process = psutil.Process(pid)
    started_at = datetime.fromtimestamp(process.create_time(), local_timezone).strftime("%Y-%m-%d %H:%M:%S")
    return SchedulerStatus(
        is_running=True,
        pid=pid,
        process_status=str(process.status()),
        started_at=started_at,
        pid_file=pid_file,
        active_jobs=counts.get("active", 0),
        paused_jobs=counts.get("paused", 0),
    )


def get_scheduler_status(
    *,
    counts: dict[str, int],
    local_timezone,
) -> SchedulerStatus:
    active_pid = _get_active_scheduler_pid()
    pid_file = _get_pid_file_path()

    if active_pid is None:
        return _build_scheduler_stopped_status(counts, pid_file)

    return _build_scheduler_running_status(active_pid, counts, pid_file, local_timezone)


def start_scheduler(
    *,
    foreground: bool,
    run_foreground: Callable[[], None],
) -> str:
    if foreground:
        run_foreground()
        return "Scheduler started in foreground"

    pid = _spawn_detached_scheduler()
    return f"Scheduler started in background (PID {pid})"


def stop_scheduler() -> bool:
    return stop_scheduler_process()


if __name__ == "__main__":
    sys.stderr.write(
        "application.py is not a CLI entrypoint.\n"
        "Use: python3 scheduler_3/scheduler.py <command>\n"
    )
    raise SystemExit(1)
