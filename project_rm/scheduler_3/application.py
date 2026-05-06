from datetime import datetime
from pathlib import Path
import sys
from typing import TYPE_CHECKING, Any, Callable

import psutil

try:
    from .lifecycle_models import SchedulerStatus
    from .process_adapter import get_active_process_pid, get_pid_file_path, remove_pid_file, stop_process, write_pid_file
except ImportError:
    from lifecycle_models import SchedulerStatus
    from process_adapter import get_active_process_pid, get_pid_file_path, remove_pid_file, stop_process, write_pid_file

if TYPE_CHECKING:
    from .job_models import Job, JobStatus


def _scheduler_module():
    """Return the live scheduler module without creating duplicate runtime state."""
    main_module = sys.modules.get("__main__")
    if main_module is not None and getattr(main_module, "__file__", "").endswith("scheduler.py"):
        return main_module

    try:
        from . import scheduler as scheduler_module
    except ImportError:
        import scheduler as scheduler_module
    return scheduler_module


def _build_scheduler_stopped_status(
    counts: dict[str, int],
    pid_file: Path,
) -> SchedulerStatus:
    """Translate raw process/job facts into the app-facing 'stopped' status model."""
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
    """Translate raw process/job facts into the app-facing 'running' status model."""
    process = psutil.Process(pid)
    started_at = datetime.fromtimestamp(process.create_time(), local_timezone)
    return SchedulerStatus(
        is_running=True,
        pid=pid,
        process_status=str(process.status()),
        started_at=started_at,
        pid_file=pid_file,
        active_jobs=counts.get("active", 0),
        paused_jobs=counts.get("paused", 0),
    )


def _build_scheduler_status(
    *,
    counts: dict[str, int],
    local_timezone,
) -> SchedulerStatus:
    """Choose stopped vs running status after checking the managed process PID file."""
    active_pid = get_active_process_pid()
    pid_file = get_pid_file_path()

    if active_pid is None:
        return _build_scheduler_stopped_status(counts, pid_file)

    return _build_scheduler_running_status(active_pid, counts, pid_file, local_timezone)


# ============================================
# Application / Orchestration - Public use cases
# Start reading internals from here.
# ============================================
def create_job(data) -> "Job":
    """
    Flow:
        add -> collect_job_input_* -> create_job
        create_job
            -> _validate_unique_job_name
            -> _build_job
            -> _schedule_single_job
            -> _insert_job
    """
    # Parsing belongs at the boundary; orchestration belongs here.
    scheduler_module = _scheduler_module()

    if scheduler_module._count_jobs() >= scheduler_module.APP_CONFIG.max_jobs:
        raise ValueError("Maximum of 100 jobs reached")

    scheduler_module._validate_unique_job_name(data.name)
    job = scheduler_module._build_job(data)
    scheduler_module._schedule_single_job(job)
    return scheduler_module._insert_job(job)


def get_jobs() -> list["Job"]:
    """
    Flow:
        list -> get_jobs
        get_jobs
            -> _fetch_jobs
    """
    scheduler_module = _scheduler_module()
    return scheduler_module._fetch_jobs()


def remove_job(identifier: str) -> bool:
    """
    Flow:
        remove -> remove_jobs
        remove_job
            -> _resolve_job_identifier
            -> _remove_job_from_db
    """
    scheduler_module = _scheduler_module()

    job = scheduler_module._resolve_job_identifier(identifier)
    job_id = job.id
    if job_id is None:
        raise ValueError(f"Job '{identifier}' not found")

    try:
        scheduler_module.scheduler.remove_job(job_id)
    except scheduler_module.JobLookupError as error:
        scheduler_module.logger.warning(f"Job {job_id} not in scheduler: {error}")

    removed = scheduler_module._remove_job_from_db(job_id)
    if removed:
        scheduler_module.logger.info(f"Job '{job.name}' ({scheduler_module.format_job_id(job_id)}) removed")

    return removed


def remove_jobs(identifiers: list[str]) -> list["Job"]:
    """
    Flow:
        remove -> remove_jobs
        remove_jobs
            -> _resolve_job_identifier
            -> remove_job
    """
    # Keep plural wrappers separate so batching does not pollute singular return shapes.
    scheduler_module = _scheduler_module()
    jobs = [scheduler_module._resolve_job_identifier(identifier) for identifier in identifiers]
    removed_jobs: list["Job"] = []
    for job in jobs:
        job_id = job.id or job.name
        if remove_job(job_id):
            removed_jobs.append(job)
    return removed_jobs


def resume_job(identifier: str) -> "Job":
    """
    Flow:
        resume -> resume_jobs
        resume_job
            -> _resolve_job_identifier
            -> scheduler.resume_job
    """
    scheduler_module = _scheduler_module()
    job = scheduler_module._resolve_job_identifier(identifier)

    if job.status is scheduler_module.JobStatus.ACTIVE:
        raise ValueError(f"Job '{job.name}' is already active")

    job_id = job.id
    if job_id is None:
        raise ValueError(f"Job '{job.name}' has no ID")

    try:
        if scheduler_module.scheduler.get_job(job_id) is None:
            if scheduler_module.scheduler.running:
                scheduler_module._schedule_single_job(job)
        else:
            scheduler_module.scheduler.resume_job(job_id)
    except scheduler_module.JobLookupError:
        pass
    except Exception as error:
        raise RuntimeError(f"Failed to resume: {error}") from error

    scheduler_module._update_job_status(job_id, scheduler_module.JobStatus.ACTIVE)
    scheduler_module.logger.info(f"Job '{job.name}' ({scheduler_module.format_job_id(job_id)}) resumed")
    return job


def resume_jobs(identifiers: list[str]) -> list["Job"]:
    """
    Flow:
        resume -> resume_jobs
        resume_jobs
            -> _resolve_job_identifier
            -> resume_job
    """
    scheduler_module = _scheduler_module()
    jobs = [scheduler_module._resolve_job_identifier(identifier) for identifier in identifiers]
    return [resume_job(job.id or job.name) for job in jobs]


def pause_job(identifier: str) -> "Job":
    """
    Flow:
        pause -> pause_jobs
        pause_job
            -> _resolve_job_identifier
            -> scheduler.pause_job
    """
    scheduler_module = _scheduler_module()
    job = scheduler_module._resolve_job_identifier(identifier)

    if job.status is scheduler_module.JobStatus.PAUSED:
        raise ValueError(f"Job '{job.name}' is already paused")

    job_id = job.id
    if job_id is None:
        raise ValueError(f"Job '{job.name}' has no ID")

    try:
        if scheduler_module.scheduler.get_job(job_id) is not None:
            scheduler_module.scheduler.pause_job(job_id)
    except scheduler_module.JobLookupError:
        pass
    except Exception as error:
        raise RuntimeError(f"Failed to pause: {error}") from error

    scheduler_module._update_job_status(job_id, scheduler_module.JobStatus.PAUSED)
    scheduler_module.logger.info(f"Job '{job.name}' ({scheduler_module.format_job_id(job_id)}) paused")
    return job


def pause_jobs(identifiers: list[str]) -> list["Job"]:
    """
    Flow:
        pause -> pause_jobs
        pause_jobs
            -> _resolve_job_identifier
            -> pause_job
    """
    scheduler_module = _scheduler_module()
    jobs = [scheduler_module._resolve_job_identifier(identifier) for identifier in identifiers]
    return [pause_job(job.id or job.name) for job in jobs]


def run_scheduler_foreground() -> None:
    """
    Flow:
        start --foreground -> run_scheduler_foreground
        run_scheduler_foreground
            -> write_pid_file
            -> scheduler.start
            -> _load_jobs_from_database
    """
    # Background mode simply spawns this exact foreground loop in another process.
    import os
    import signal
    import threading
    import time

    scheduler_module = _scheduler_module()

    existing_pid = get_active_process_pid()
    if existing_pid is not None:
        raise RuntimeError(f"Scheduler is already running (PID {existing_pid})")

    stop_event = threading.Event()

    def _handle_shutdown_signal(signum: int, frame: Any) -> None:
        del frame
        stop_event.set()
        scheduler_module.logger.info(f"Received signal {signum}, shutting down scheduler")

    previous_sigint = signal.getsignal(signal.SIGINT)
    previous_sigterm = signal.getsignal(signal.SIGTERM)

    try:
        signal.signal(signal.SIGINT, _handle_shutdown_signal)
        signal.signal(signal.SIGTERM, _handle_shutdown_signal)
        write_pid_file(os.getpid())

        if not scheduler_module.scheduler.running:
            scheduler_module.scheduler.start()
            scheduler_module.logger.info("Scheduler daemon started")
        else:
            scheduler_module.logger.info("Scheduler already running")

        scheduler_module._load_jobs_from_database()

        while not stop_event.is_set():
            time.sleep(1)
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)

        if scheduler_module.scheduler.running:
            scheduler_module.logger.info("Stopping scheduler...")
            scheduler_module.scheduler.shutdown(wait=True)
            scheduler_module.logger.info("Scheduler stopped")

        remove_pid_file()


def start_scheduler(foreground: bool = False) -> str:
    """
    Flow:
        start -> start_scheduler
        start_scheduler
            -> run_scheduler_foreground | spawn_detached_process
    """
    # Same use-case, two runtime modes: attached foreground or detached background.
    if foreground:
        run_scheduler_foreground()
        return "Scheduler started in foreground"

    scheduler_module = _scheduler_module()
    pid = scheduler_module.spawn_detached_process()
    return f"Scheduler started in background (PID {pid})"


def stop_scheduler() -> bool:
    return stop_process()
def get_scheduler_status() -> SchedulerStatus:
    """
    Flow:
        status -> get_scheduler_status
        get_scheduler_status
            -> _count_jobs_by_status
            -> _build_scheduler_status
    """
    # Status is derived from live process state plus current DB counts.
    scheduler_module = _scheduler_module()
    return _build_scheduler_status(
        counts=scheduler_module._count_jobs_by_status(),
        local_timezone=scheduler_module.LOCAL_TZ,
    )
