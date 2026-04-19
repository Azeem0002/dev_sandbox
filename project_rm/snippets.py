#!/usr/bin/env python3

import sqlite3
from zoneinfo import ZoneInfo
from pathlib import Path
from loguru import logger
from dataclasses import dataclass
from datetime import datetime
from platformdirs import PlatformDirs
import typer
import uuid
import time
import shlex
import subprocess
from tenacity import retry, stop_after_attempt, wait_exponential


# APSCHEDULER
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger

# ============================================
# CONFIG
# ============================================

APP_NAME = "scheduler"
APP_AUTHOR = "Al-Azeem"

STORAGE_TZ = ZoneInfo("UTC")  # DB storage # UTC: Coordinated universal time
LOCAL_TZ = ZoneInfo("Africa/Lagos")  # User display

# Platform-appropriate data directory
dirs = PlatformDirs(APP_NAME, APP_AUTHOR)
DB_PATH = Path(dirs.user_data_dir) / "jobs.db"

scheduler = BackgroundScheduler(timezone=LOCAL_TZ)

# =======================================================
#   SETUP ENVIRONMENT & LOGGING CONFIGURATION
# =======================================================

def _setup_env()-> Path:

    ...

def _setup_logger(file_log: Path)-> None:
   ...
# ============================================
# MODELS
# ============================================
@dataclass
class AddJobInput: #Job application form
    """User's request (raw input)"""
    name: str
    command: str
    schedule_type: str  # "once" | "weekly"
    day_of_week: int | None = None  # 1–7
    scheduled_time: str | None = None

@dataclass
class Job: # Employee record after hiring
    """Stored entity in database"""

    id: str | None           # Database primary key (None until saved)
    name: str                 # Human-readable label ("Daily Backup")
    command: str              # Shell command to execute
    schedule_type: str        # "once" or "weekly"
    day_of_week: int | None   # 1=Monday..7=Sunday (only for weekly)
    scheduled_time: str | None      # "21:00" or "2026-04-14T15:30:00"
    next_runtime: datetime   # Pre-calculated UTC timestamp (core driver!)
    status: str = "active"    # "active" or "paused"

# ============================================
# RESPONSIBILITIES (pure logic)
# ============================================
def _create_trigger(schedule_type: str, day: int | None, time_str: str | None):
    """APScheduler owns scheduling logic now"""

    if schedule_type == "once":
        if not time_str:
            raise ValueError("Time required for 'once'")
        
        target = datetime.fromisoformat(time_str)

        if target.tzinfo is None:
            target = target.replace(tzinfo=LOCAL_TZ)

        if target <= datetime.now(LOCAL_TZ):
            raise ValueError("Time must be in future")

        return DateTrigger(run_date=target, timezone=LOCAL_TZ)

    if schedule_type == "weekly":
        if day is None or time_str is None:
            raise ValueError("Weekly requires day and time")
    
        hour, minute = map(int, time_str.split(":"))

        days = ["mon","tue","wed","thu","fri","sat","sun"]

        if isinstance(days, list):
            # Multiple days: "mon,wed,fri"
            day_names = [["mon","tue","wed","thu","fri","sat","sun"][d-1] for d in days]
            day_str = ",".join(day_names)
        else:
            # Single day
            day_str = ["mon","tue","wed","thu","fri","sat","sun"][days-1]

        

        if day is None or not (1 <= day <= 7):
            raise ValueError("day_of_week must be 1-7")
            
        return CronTrigger(
            day_of_week=day_str,
            hour=hour,
            minute=minute,
            timezone=LOCAL_TZ
        )

    raise ValueError("Invalid schedule_type")

def _get_next_run(trigger, schedule_type):
    """Ask APScheduler instead of guessing"""

    if schedule_type == "once":
        next_run = trigger.run_date
    else:
        next_run = trigger.get_next_fire_time(None, datetime.now(LOCAL_TZ))

    return next_run.astimezone(STORAGE_TZ)


# ---SECURITY FIX----
def _validate_command(cmd: str):
    if not cmd.strip():
        raise ValueError("Command cannot be empty")
    
    # Hard block shell injection characters
    forbidden = [";", "&", "|", "\n", "\r", "`", "$(", ">","<"]
    for f in forbidden:
        if f in cmd:
            raise ValueError(f"Unsafe pattern detected: {f}")
    

def _execute_job_command(command: str) -> None:
    """Execute a scheduled job with proper logging"""
    
    returncode = None 
    logger.info(f"🚀 STARTING: {command[:50]}...")
    commands = shlex.split(command)

    try:
        result = subprocess.run(
            commands,
            capture_output=True,
            text=True,
            timeout=300,
            shell=False
        )
        returncode = result.returncode

        if returncode == 0:
            logger.info(f"SUCCESS: {result.stdout.strip()}")
        else:
            logger.error(f"FAILED ({returncode}): {result.stderr.strip()}")

    except subprocess.TimeoutExpired:
        logger.error("TIMEOUT")

    except FileNotFoundError:
        logger.error(f"NOT FOUND: {commands[0] if commands else 'unknown'}")

    except Exception as e:
        logger.error(f"ERROR: {e}")

    finally:
        logger.info(f"COMPLETED: exit {returncode}")

def _build_job(data: AddJobInput) -> Job:
    schedule_type = data.schedule_type.lower().strip()

    if schedule_type not in ("once","weekly"):
        raise ValueError("Invalid schedule type")

    _validate_command(data.command)

    trigger = _create_trigger(
        schedule_type,
        data.day_of_week,
        data.scheduled_time
    )

    next_run = _get_next_run(trigger, schedule_type)

    return Job(
        id=str(uuid.uuid4()),
        name=data.name.strip(),
        command=data.command,
        schedule_type=schedule_type,
        day_of_week=data.day_of_week,
        scheduled_time=data.scheduled_time,
        next_runtime=next_run,
        status= "active",
    )

# ============================================
# PERSISTENCE (I/O operations)
# ============================================

def _init_db():
   ...

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
def _insert_job(job: Job) -> Job:
    with sqlite3.connect(DB_PATH) as conn:

        if job.id is None:
            job.id = str(uuid.uuid4())

        cursor = conn.execute("""
            INSERT INTO jobs (
                id, name, command, schedule_type,
                day_of_week, scheduled_time,
                next_run_time, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job.id,
            job.name,
            job.command,
            job.schedule_type,
            job.day_of_week,
            job.scheduled_time,
            job.next_runtime.isoformat(),
            job.status
        ))

        logger.info(f"Job saved: {job.name} (ID: {job.id})")
        return job

def _fetch_jobs():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM jobs").fetchall()

    return [
        Job(
            id=r["id"],
            name=r["name"],
            command=r["command"],
            schedule_type=r["schedule_type"],
            day_of_week=r["day_of_week"],
            scheduled_time=r["scheduled_time"],
            next_runtime=datetime.fromisoformat(r["next_run_time"]),
            status=r["status"]
        )
    for r in rows
]


# ============================================
# ORCHESTRATION (public API)
# ============================================

def add_job(data: AddJobInput) -> Job:
    """Single source of truth for adding jobs"""
    job = _build_job(data)
    trigger = _create_trigger(job.schedule_type, job.day_of_week, job.scheduled_time)
    scheduler.add_job(...)
    return _insert_job(job)

def start_scheduler() -> None:
    """Start the scheduler daemon"""
    jobs = _fetch_jobs()
    for job in jobs:
        if job.status == "active":
            _schedule_job(job)  # Helper function
    
    if not scheduler.running:
        scheduler.start()
        logger.info(f"Scheduler started with {len(jobs)} jobs")



def list_jobs():
    """Public function: Retrieve all jobs"""
    jobs = _fetch_jobs()
    if len(jobs) > 100:
        raise ValueError("Too many jobs")
    return jobs


def start_job():

    jobs = _fetch_jobs() # load from DB

    logger.info(f"Loading {len(jobs)} jobs")

    for job in jobs:
        trigger = _create_trigger(
            job.schedule_type,
            job.day_of_week,
            job.scheduled_time
        )

        scheduler.add_job(
            _execute_job_command,
            trigger=trigger,
            id=job.id,
            name=job.name,
            kwargs={"command": job.command},
            replace_existing=True,
            coalesce=True,
            max_instances=1
        )

    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started")
    else:
        typer.echo("Scheduler already running")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        scheduler.shutdown()

# ===== REMOVE JOB =====
def remove_job(job_id: str) -> bool:
    """Remove a job from scheduler and database"""
    try:
        # Remove from APScheduler
        scheduler.remove_job(job_id)
    except Exception as e:
        logger.warning(f"Job {job_id} not in scheduler: {e}")
    
    # Remove from database
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        return cursor.rowcount > 0

def stop_scheduler(wait: bool = True):
    """Gracefully stop the scheduler"""
    if scheduler.running:
        logger.info("Stopping scheduler...")
        scheduler.shutdown(wait=wait)
        logger.info("Scheduler stopped")
    else:
        logger.info("Scheduler not running")

# ============================================
# CLI - Thin wrapper around orchestration
# ============================================

app = typer.Typer(
    name="scheduler",
    help="Cross-platform job scheduler",
    )


@app.callback()
def init():
    file_log = _setup_env()
    _setup_logger(file_log)
    _init_db()

@app.command()
def add(
    name: str = typer.Argument(None),
    command: str = typer.Argument(None),
    schedule_type: str = typer.Option(None, "--type"),
    day_of_week: int = typer.Option(None, "--day"),
    scheduled_time: str = typer.Option(None, "--time"),
    interactive: bool = typer.Option(False, "--interactive", "-i")
):


    """Parse arguments, call orchestrator, display result"""
    try:
        job = add_job(AddJobInput(...))
        typer.echo(f"✓ Created {job.id[:8]}")
    except ValueError as e:
        typer.echo(f"✗ {e}", err=True)
        raise typer.Exit(1)


@app.command()
def list():
    jobs = list_jobs()

    for job in jobs:
        job_id = job.id[:8] if job.id else "N/A"
        typer.echo(f"{job_id} {job.name} -> {job.next_runtime}")


@app.command()
def start():
    """Start the scheduler"""
    start_scheduler()
    typer.echo("✓ Scheduler started")
    # Keep alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_scheduler()

@app.command()
def remove(
    job_id: str = typer.Argument(..., help="Job ID to remove"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation")
):
    """Remove a scheduled job"""
    if not force:
        if not typer.confirm(f"Remove job {job_id[:8]}?"):
            typer.echo("Cancelled")
            raise typer.Exit(0)
    
    if remove_job(job_id):
        typer.echo(f"✓ Job {job_id[:8]} removed")
    else:
        typer.echo(f"✗ Job {job_id[:8]} not found", err=True)
        raise typer.Exit(1)

@app.command()
def stop():
    """Stop the scheduler daemon"""
    try:
        stop_scheduler()
        typer.echo("✓ Scheduler stopped")
    except Exception:
        typer.echo("Job not found in scheduler")
# ============================================
# ENTRY
# ============================================
if __name__ == "__main__":
    app()