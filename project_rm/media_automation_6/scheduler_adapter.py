"""In-process scheduler adapter for media_automation_6."""

from apscheduler.schedulers.background import BackgroundScheduler
from loguru import logger

try:
    from .models import SchedulerStatus
except ImportError:
    from models import SchedulerStatus


# ============================================
# Scheduler adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================
scheduler = BackgroundScheduler()


def _start_scheduler(job_func, *, interval_minutes: int) -> SchedulerStatus:
    """Start one recurring background job if it is not already running."""
    # The scheduler checks for due posts; the app still stores the real schedule in SQLite.
    # This keeps APScheduler as a timer engine, not the source of truth.
    if not scheduler.get_job("publish_due_posts"):
        scheduler.add_job(job_func, "interval", minutes=interval_minutes, id="publish_due_posts", replace_existing=True, coalesce=True, max_instances=1)
    if not scheduler.running:
        scheduler.start()
        logger.info("Media automation scheduler started")
    return _get_scheduler_status()


def _stop_scheduler() -> SchedulerStatus:
    """Stop the background scheduler if it is running."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Media automation scheduler stopped")
    return _get_scheduler_status()


def _get_scheduler_status() -> SchedulerStatus:
    """Return small scheduler status for API responses."""
    return SchedulerStatus(running=scheduler.running, scheduled_jobs=len(scheduler.get_jobs()))


# ============================================
# Public adapter API - stable reusable surface
# ============================================
def start_scheduler(job_func, *, interval_minutes: int) -> SchedulerStatus:
    """Public wrapper for starting recurring publishing checks."""
    return _start_scheduler(job_func, interval_minutes=interval_minutes)


def stop_scheduler() -> SchedulerStatus:
    """Public wrapper for stopping recurring publishing checks."""
    return _stop_scheduler()


def get_scheduler_status() -> SchedulerStatus:
    """Public wrapper for reading scheduler status."""
    return _get_scheduler_status()
