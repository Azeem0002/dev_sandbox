#!/usr/bin/env python3

"""
sudo cp scheduler.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable scheduler
sudo systemctl start scheduler
"""
import sqlite3
from zoneinfo import ZoneInfo
from pathlib import Path
from loguru import logger
from datetime import datetime
from enum import StrEnum
from dataclasses import dataclass
import os
import threading
import typer
import time
import shlex
import uuid
import json
import signal
import subprocess
import psutil
from tenacity import retry, stop_after_attempt, wait_exponential
from typing import Any, Callable, cast


# APSCHEDULER
from apscheduler.schedulers.background import BackgroundScheduler  # The timer engine
from apscheduler.triggers.date import DateTrigger                  # "Run once at X time"
from apscheduler.triggers.cron import CronTrigger                  # "Run every Monday at 9"
from apscheduler.jobstores.base import JobLookupError               # "Job not found" error

# ============================================
# CONFIG
# ============================================

from pydantic import BaseModel, ConfigDict, field_validator, model_validator
try:
    from .application import (
        get_scheduler_status as _get_scheduler_status,
        start_scheduler as _start_scheduler,
        stop_scheduler as _stop_scheduler,
    )
    from .lifecycle_models import SchedulerStatus
    from .platform_adapter import _detect_platform
    from .process_adapter import (
        _get_active_scheduler_pid,
        _get_pid_file_path,
        _remove_pid_file,
        _spawn_detached_scheduler,
        _write_pid_file,
        stop_scheduler_process,
    )
    from .runtime_support import _get_platform_dirs, _setup_env, _setup_logger
    from .systemd_adapter import install_scheduler_service
except ImportError:
    from application import (
        get_scheduler_status as _get_scheduler_status,
        start_scheduler as _start_scheduler,
        stop_scheduler as _stop_scheduler,
    )
    from lifecycle_models import SchedulerStatus
    from platform_adapter import _detect_platform
    from process_adapter import (
        _get_active_scheduler_pid,
        _get_pid_file_path,
        _remove_pid_file,
        _spawn_detached_scheduler,
        _write_pid_file,
        stop_scheduler_process,
    )
    from runtime_support import _get_platform_dirs, _setup_env, _setup_logger
    from systemd_adapter import install_scheduler_service

class AppConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    app_name: str = "scheduler"
    app_author: str = "Al-Azeem"
    storage_timezone: str = "UTC" # for database 
    local_timezone: str = "Africa/Lagos"
    max_jobs: int = 100


APP_CONFIG = AppConfig()
STORAGE_TZ = ZoneInfo(APP_CONFIG.storage_timezone)
LOCAL_TZ = ZoneInfo(APP_CONFIG.local_timezone)

# Platform-appropriate data directory
dirs = _get_platform_dirs()
DB_PATH = Path(dirs.user_data_dir) / "jobs.db"

scheduler = BackgroundScheduler(timezone=LOCAL_TZ)

# ============================================
# MODELS
# ============================================

# Object: An instance of a class, Noun: Name of thing
class ScheduleType(StrEnum):
    ONCE = "once"
    WEEKLY = "weekly"


class JobStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"


class AddJobInput(BaseModel): #Job application form
    """User's request (raw input)"""

    model_config = ConfigDict(str_strip_whitespace=True) 
    # Automatically applies .strip() to all string fields before validations but does nit validate emptiness

    name: str
    command: str # raw CLI input at the boundary
    schedule_type: ScheduleType
    days_of_week: list[int] | None = None  # 1–7
    scheduled_time: str | None = None

    @field_validator("name") # Inspecting each ingredient separately
    @classmethod  # Called on the class, before instance exists
    def _adapt_name_for_model(cls, value: str) -> str: # cls: because the instance doesn't exist yet
        return _require_non_empty_text(value, "Name")

    @field_validator("command", mode="before") 
    # field_validator must match the exact field name in your model
    @classmethod
    def _adapt_command_for_model(cls, value: Any) -> str:
        # Keep 'type: Any' for mode="before". data could be any type
        return _normalize_command_text(value)

    @field_validator("schedule_type", mode="before") # mode="before": Before Pydantic type conversion
    @classmethod
    def _adapt_schedule_type_for_model(cls, value: Any) -> ScheduleType:
        # Any acknowledges "we don't know what we'll get yet" before Pydantic coerces to enum.
        if not isinstance(value, str): # validates correct type
            raise ValueError("Schedule type must be text")
        return _validate_schedule_type(value)

    @field_validator("days_of_week")
    @classmethod
    def _adapt_days_for_model(cls, value: list[int] | None) -> list[int] | None:
        return _normalize_days_list(value)

    @field_validator("scheduled_time")
    @classmethod
    def _adapt_scheduled_time_for_model(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @model_validator(mode="after") # model_validator: checking multiple fields at once. comes last after all field validations
    # mode="after": After pydantic type conversion 
    def _validate_schedule_shape(self) -> "AddJobInput": #self: after the instance exists
        if self.schedule_type is ScheduleType.ONCE:  # checks if user is using the schedule type once.
            if not self.scheduled_time:  # once jobs need a time
                raise ValueError("One-time jobs require a scheduled time")
            if self.days_of_week is not None:  # once jobs can't have days
                raise ValueError("One-time jobs do not accept days_of_week")
            return self  # valid, stop here

        if not self.days_of_week:  # weekly needs days
            raise ValueError("Weekly jobs require at least one day")
        if not self.scheduled_time:  # weekly also needs a time
            raise ValueError("Weekly jobs require a scheduled time")
        return self  # valid, stop here
    # self is the validated instance. Returning it continues the validation chain.

@dataclass
class Job: # Employee record after hiring
    """Stored entity in database"""

    id: str | None          # Database primary key (None until saved)
    name: str                 # Human-readable label ("Daily Backup")
    command: list[str]              # Shell command to execute
    schedule_type: ScheduleType
    days_of_week: list[int] | None   # 1=Monday..7=Sunday (only for weekly)
    scheduled_time: datetime | None      # "21:00" or "2026-04-14T15:30:00"
    next_runtime: datetime   # Pre-calculated UTC timestamp (core driver!)
    status: JobStatus = JobStatus.ACTIVE


# ============================================
# RESPONSIBILITIES (pure core logic)
# ============================================

# Core input: General type, output: Parsed/Validated values 
# Auto convert/force one type to another
def _coerce_job_scheduled_time( 
    schedule_type: ScheduleType,
    value: str | datetime | None
) -> datetime | None:
    """Normalize persisted/input schedule values into Job's datetime field.
        A universal translator that converts different time input formats into one standard format (UTC datetime)
    """
    if value is None:
        return None  # Nothing to convert

    if isinstance(value, datetime):
        parsed = value  # Already datetime "2026-04-22T15:30", no parsing needed

    elif schedule_type is ScheduleType.ONCE:  # String for once
        parsed = datetime.fromisoformat(value)  # Converts ISO str format "2026-04-22T15:30" → datetime(2026, 4, 22, 15, 30) datetime object
        # fromisoformat(): string → datetime
        # ISO = International Organization for Standardization

    else:   # String for weekly
        hour, minute = map(int, value.split(":"))  # "09:00" → hour=9, minute=0
        # Weekly jobs only need a stable local time-of-day anchor.
        # map(): Apply this function to every item in this list. map(int) converts the splitted time values both to int

        # Creates a fake date (year 2000) with real time
        parsed = datetime(2000, 1, 3, hour, minute, tzinfo=LOCAL_TZ)
        # Why year 2000? It's a stable anchor—weekly only cares about time-of-day
        # Meaning: “We don’t care about the date — only time of day”
        # So they pick a fake anchor date.
        # Weekly jobs: repeat every week.we only care about TIME, not DATE

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=LOCAL_TZ)  #“If time has no timezone, assume/attach local timezone
    return parsed.astimezone(LOCAL_TZ)  # Convert time/clock into local timezone safely
    # This prevents: wrong scheduling due to timezone mismatch
    # Result: datetime(2026, 4, 24, 15, 30, tzinfo=ZoneInfo("Africa/Lagos"))

# Persistence layer
def _serialize_scheduled_time(value: datetime | None) -> str | None:
    """
    STORAGE FORMATTER: datetime → string for DB / JSON
    """
    if value is None:
        return None
    return value.isoformat() # isoformat(): Converts Datetime → string (for DB / JSON)
    # isoformat(): Machine storage (database)

def _format_scheduled_time(job: Job) -> str:
    """
    DISPLAY FORMATTER: datetime → UI human-readable string
    """
    if job.scheduled_time is None:
        return "-"
    if job.schedule_type is ScheduleType.WEEKLY:
        # strftime(): Human display (CLI)
        return job.scheduled_time.astimezone(LOCAL_TZ).strftime("%H:%M")  # strftime("%H:%M"): convert datetime → "14:30"
    return job.scheduled_time.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M") # .astimezone(): converts datetime to the current timezone

def _create_trigger(
    schedule_type: ScheduleType,
    days: list[int] | None,
    scheduled_time: datetime | None
):
    """
    Create APScheduler trigger for single or multiple days.
    
    Args:
        days: Single day (as list with one item) or multiple days
              Example: [3] for Wednesday, [1,3,5] for Mon/Wed/Fri
    """
    if schedule_type is ScheduleType.ONCE:
        if not scheduled_time:
            raise ValueError("Time required for 'once'")

        target = scheduled_time.astimezone(LOCAL_TZ)
        if target <= datetime.now(LOCAL_TZ):
            raise ValueError("Time must be in future")

        return DateTrigger(run_date=target, timezone=LOCAL_TZ)

    if schedule_type is ScheduleType.WEEKLY:
        if not days or not scheduled_time:
            raise ValueError("Weekly requires day(s) and time")

        # Validate all days
        for d in days:
            if not (1 <= d <= 7): # day must be between 1-7
                # day is greater than or equal to 1 and less than or equal to 7
                raise ValueError(f"Invalid day: {d}. Must be 1-7")

        local_time = scheduled_time.astimezone(LOCAL_TZ)
        hour = local_time.hour
        minute = local_time.minute
        days_map = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

        # Convert to cron string: "mon,wed,fri"
        cron_days = ",".join(days_map[d-1] for d in days)

        return CronTrigger(
            day_of_week=cron_days,
            hour=hour,
            minute=minute,
            timezone=LOCAL_TZ
        )
    
    raise ValueError(f"Invalid schedule_type: {schedule_type}")

def _get_next_run(trigger, schedule_type: ScheduleType):
    """Ask APScheduler instead of guessing"""

    if schedule_type is ScheduleType.ONCE:
        next_run = trigger.run_date
    else:
        next_run = trigger.get_next_fire_time(None, datetime.now(LOCAL_TZ))

    return next_run.astimezone(STORAGE_TZ)


def _execute_job_commands(commands: list[str]) -> None:
    """Execute a scheduled job with proper logging"""
    
    returncode = -1 # None: causes issues in finally block
    logger.info(f"🚀 STARTING: {commands[:50]}...")

    try:
        result = subprocess.run(
            commands,
            capture_output=True,
            text=True,
            timeout=300,
            shell=False,
            start_new_session=True
        )
        returncode = result.returncode

        if returncode == 0:
            logger.info(f"SUCCESS: {result.stdout.strip()}")
        else:
            logger.error(f"FAILED ({returncode}): {result.stderr.strip()}")

    except subprocess.TimeoutExpired:
        logger.error("⏰ TIMEOUT after 300s")
    except FileNotFoundError:
        logger.error(f"🔍 NOT FOUND: {commands[0] if commands else 'unknown'}")
    except (RuntimeError, Exception) as e:
        logger.error(f"💥 ERROR: {type(e).__name__}: {e}")
    finally:
        logger.info(f"🏁 COMPLETED: exit {returncode}")

def _build_job(data: AddJobInput) -> Job:
    """Transform input into complete Job object"""
    schedule_type = data.schedule_type
    scheduled_time = _coerce_job_scheduled_time(schedule_type, data.scheduled_time)
    command_parts = _normalize_command_input(data.command)

    trigger = _create_trigger(
        schedule_type,
        data.days_of_week,
        scheduled_time
    )

    next_run = _get_next_run(trigger, schedule_type)

    return Job(
        id=str(uuid.uuid4()),
        name=data.name.strip(),
        command=command_parts,
        schedule_type=schedule_type,
        days_of_week=data.days_of_week,
        scheduled_time=scheduled_time,
        next_runtime=next_run,
        status=JobStatus.ACTIVE
    )

def _schedule_single_job(job: Job) -> None:
    """Helper: Add one job to APScheduler"""

    if job.status is not JobStatus.ACTIVE:
        return
    
    # Attributes: Data attached to the object class. Adjective: describes the thing
    trigger = _create_trigger(
        job.schedule_type,
        job.days_of_week,
        job.scheduled_time
    )
    scheduler.add_job(
        _execute_job_commands,
        trigger=trigger,
        id=job.id,
        name=job.name,
        kwargs={"commands": job.command},
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )    

def _resolve_job_identifier(identifier: str) -> Job:
    """
    Resolve: figure out user input (full id, short id, or name) → full job_id
    """
    token = identifier.strip()
    jobs = _fetch_jobs()

    # 1. Exact ID match
    for job in jobs:
        if job.id == identifier:
            return job
        
    # Try short ID prefix (must be at least 4 chars to avoid ambiguity)
    if len(identifier) >= 4:
        matches = [j for j in jobs if j.id and j.id.startswith(identifier)]
        if len(matches) == 1:
            return matches[0]
        elif len(matches) > 1:
            raise ValueError(f"Ambiguous prefix '{token}'. Use more characters or full ID.")
        
     # Try exact name match (case-insensitive)
    matches = [j for j in jobs if j.name.lower() == identifier.lower()]
    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        raise ValueError(f"Multiple jobs named '{token}'. Use ID instead.")
    
    raise ValueError(f"Job '{token}' not found")
    
def _find_job_by_name(name: str) -> Job | None:
    normalized_name = _normalize_name_key(name)
    for job in _fetch_jobs():
        if _normalize_name_key(job.name) == normalized_name:
            return job
    return None

def _format_job_id(job_id: str | None) -> str:
    """Safely format job ID for display"""
    if job_id is None:
        return "NO_ID"
    return job_id[:8]

def _status_label(status: JobStatus) -> str:
    if status is JobStatus.PAUSED:
        return "⏸ paused"
    return "▶ active"

def _delete_jobs_by_ids(conn: sqlite3.Connection, job_ids: list[str]) -> int:
    if not job_ids:
        return 0
    conn.executemany("DELETE FROM jobs WHERE id = ?", [(job_id,) for job_id in job_ids])
    return len(job_ids)

def _cleanup_jobs_table(conn: sqlite3.Connection) -> int:
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, name, next_run_time
        FROM jobs
        ORDER BY next_run_time, id
    """).fetchall()

    invalid_ids: list[str] = []
    duplicate_ids: list[str] = []
    seen_names: set[str] = set()

    for row in rows:
        job_id = cast(str | None, row["id"])
        raw_name = cast(str, row["name"] or "")

        try:
            normalized_name = _normalize_name_key(raw_name)
        except ValueError:
            if job_id:
                invalid_ids.append(job_id)
            continue

        if normalized_name in seen_names:
            if job_id:
                duplicate_ids.append(job_id)
            continue

        seen_names.add(normalized_name)

    removed_count = _delete_jobs_by_ids(conn, invalid_ids + duplicate_ids)

    for job_id in invalid_ids:
        logger.warning(f"Removed invalid job with empty name ({_format_job_id(job_id)})")
    for job_id in duplicate_ids:
        logger.warning(f"Removed duplicate job name ({_format_job_id(job_id)})")

    return removed_count

# --- PERSISTENCE (I/O operations) ---

def _init_db()-> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as conn:
        
        
        # === PERFORMANCE & SAFETY SETTINGS ===
        conn.execute("PRAGMA journal_mode=WAL;") # Concurrent reads/writes
        conn.execute("PRAGMA synchronous=NORMAL;") # Balance safety/speed
        conn.execute("PRAGMA cache_size=-10000;") # 10MB cache
        conn.execute("PRAGMA temp_store=MEMORY;") # Temp tables in RAM
        conn.execute("PRAGMA busy_timeout=5000;") # Wait 5s on locks
        

        conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            name TEXT,
            command TEXT,
            schedule_type TEXT,
            days_of_week TEXT,
            scheduled_time TEXT,
            next_run_time TEXT,
            status TEXT NOT NULL DEFAULT 'active'
        )
        """)

        removed_count = _cleanup_jobs_table(conn)
        if removed_count:
            logger.warning(f"Removed {removed_count} invalid/duplicate job(s) during startup cleanup")

        # === INDEXES ===
        conn.execute("CREATE INDEX IF NOT EXISTS idx_next_run ON jobs(next_run_time)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON jobs(status)")
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_unique_name
            ON jobs(lower(trim(name)))
            WHERE trim(name) <> ''
        """)

        logger.debug("Database Initialized")

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
# tenacity retry: Scheduler calling Database =  Machine calling machine:
# Persistence input/output: dataclass
def _insert_job(job: Job) -> Job:
    """Save job to database with retry"""

    with sqlite3.connect(DB_PATH) as conn:
        
        try:
            conn.execute("""
                INSERT INTO jobs (
                    id, name, command, schedule_type,
                    days_of_week, scheduled_time,
                    next_run_time, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job.id,
                job.name,
                json.dumps(job.command), # dumps: stores to db
                job.schedule_type.value,
                json.dumps(job.days_of_week), # if you serialize → always deserialize symmetrically
                _serialize_scheduled_time(job.scheduled_time),
                job.next_runtime.isoformat(), # machine language format
                job.status.value
            ))
        except sqlite3.IntegrityError as e:
            raise ValueError(f"Job name '{job.name}' already exists") from e

        logger.info(f"Job saved: {job.name} (ID: {job.id})")
        return job

def _fetch_jobs() -> list[Job]:
    """Retrieve all jobs from database ordered by next run time
       Read from database fpr persistence
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT id, name, command, schedule_type, 
            days_of_week, scheduled_time, next_run_time, status 
            FROM jobs 
            ORDER BY next_run_time
        """).fetchall()
    
    return [
        Job(
            id=r["id"],
            name=r["name"],
            command=json.loads(r["command"]),  # loads: retrieve from db
            schedule_type=ScheduleType(r["schedule_type"]),
            days_of_week=json.loads(r["days_of_week"]) if r["days_of_week"] else None,
            scheduled_time=_coerce_job_scheduled_time(
                ScheduleType(r["schedule_type"]),
                r["scheduled_time"]
            ),
            next_runtime=datetime.fromisoformat(r["next_run_time"]),
            status=JobStatus(r["status"])
        )
        for r in rows  # List comprehension is fine with proper parsing
    ]
    

def _remove_job_from_db(job_id: str) -> bool:
    """Remove/delete job from database"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        return cursor.rowcount > 0

def _load_jobs_from_database() -> int:
    """Restore all active jobs from database on startup"""

    jobs = _fetch_jobs()
    loaded = 0
    
    if not jobs:
        logger.info("No jobs found in database")
        return 0
    
    # ✅ Show what's being loaded
    logger.info(f"Loading {len(jobs)} job(s) from database:")
    
    for job in jobs:
        if job.status is JobStatus.ACTIVE:
            try:
                _schedule_single_job(job)
                loaded += 1
                
                # ✅ Safe ID formatting
                display_id =  _format_job_id(job.id)

                # ✅ Show job details
                next_run = job.next_runtime.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")
                logger.info(f"  ✓ [{display_id}] {job.name} → {next_run}")
                
            except ValueError as e:
                display_id =  _format_job_id(job.id)
                logger.error(f"  ✗ [{display_id}] Invalid config: {e}")
            except Exception as e:
                display_id =  _format_job_id(job.id)
                logger.error(f"  ✗ [{display_id}] Failed to load  job: {type(e).__name__}")
        else:
            display_id =  _format_job_id(job.id)
            logger.debug(f"  ⏸ [{display_id}] {job.name} (paused)")

    return loaded


def _count_jobs() -> int:
    """Count total jobs in database"""

    # O(1), database optimized, constant time
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("SELECT COUNT(*) FROM jobs")
        return cursor.fetchone()[0]


def _count_jobs_by_status() -> dict[str, int]:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("""
            SELECT status, COUNT(*) AS total
            FROM jobs
            GROUP BY status
        """).fetchall()

    counts = {JobStatus.ACTIVE.value: 0, JobStatus.PAUSED.value: 0}
    for status, total in rows:
        counts[str(status)] = int(total)
    return counts


def get_scheduler_status() -> SchedulerStatus:
    return _get_scheduler_status(
        counts=_count_jobs_by_status(),
        local_timezone=LOCAL_TZ,
    )


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
        active_jobs=counts.get(JobStatus.ACTIVE.value, 0),
        paused_jobs=counts.get(JobStatus.PAUSED.value, 0),
    )


def _build_scheduler_running_status(
    pid: int,
    counts: dict[str, int],
    pid_file: Path,
) -> SchedulerStatus:
    process = psutil.Process(pid)
    started_at = datetime.fromtimestamp(process.create_time(), LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")  # strftime(): UI format
    return SchedulerStatus(
        is_running=True,
        pid=pid,
        process_status=str(process.status()),
        started_at=started_at,
        pid_file=pid_file,
        active_jobs=counts.get(JobStatus.ACTIVE.value, 0),
        paused_jobs=counts.get(JobStatus.PAUSED.value, 0),
    )

def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned

def _require_non_empty_text(value: str, field_name: str) -> str:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned:
        raise ValueError(f"{field_name} cannot be empty")
    return cleaned

def _normalize_name_key(value: str) -> str:
    return _require_non_empty_text(value, "Name").casefold()

def _validate_command_parts(value: list[str]) -> list[str]:
    if not value:
        raise ValueError("Command cannot be empty")

    cleaned = [part.strip() for part in value if part.strip()]
    if not cleaned:
        raise ValueError("Command cannot be empty")

    forbidden = [";", "&", "|", "\n", "\r", "`", "$(", ">", "<"]
    for part in cleaned:
        for token in forbidden:
            if token in part:
                raise ValueError(f"Unsafe pattern: {token}")

    return cleaned


def _normalize_command_text(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Command must be text")
    return _require_non_empty_text(value, "Command")


def _normalize_command_input(value: Any) -> list[str]:
    raw_value = _normalize_command_text(value)
    parts = shlex.split(raw_value)
    return _validate_command_parts(parts)

def _normalize_days_list(value: list[int] | None) -> list[int] | None:
    if value is None:
        return None

    normalized = sorted(set(value))
    for day in normalized:
        if not (1 <= day <= 7):
            raise ValueError(f"Day {day} must be 1-7")
    return normalized

def _validate_unique_job_name(value: str) -> str:
    cleaned = _require_non_empty_text(value, "Name")
    existing = _find_job_by_name(cleaned)
    if existing is not None:
        raise ValueError(
            f"Job name '{cleaned}' already exists ({_format_job_id(existing.id)}). Use a different name."
        )
    return cleaned

# ===== VALIDATORS (Pure functions, no I/O) =====

def _validate_date(value: str) -> str:
    """Parse flexible date formats, return YYYY-MM-DD"""
    formats = ["%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"]
    for fmt in formats:
        try:
            parsed = datetime.strptime(value.strip(), fmt)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError("Use YYYY-MM-DD (e.g., 2026-04-18)")


def _validate_time_12h(value: str) -> str:
    """Parse 12-hour time, return HH:MM (24-hour)"""
    try:
        parsed = datetime.strptime(value.strip(), "%I:%M %p")
        return parsed.strftime("%H:%M")
    except ValueError:
        raise ValueError("Use HH:MM AM/PM (e.g., 03:00 PM)")


def _validate_time_24h(value: str) -> str:
    """Parse 24-hour time, return HH:MM"""
    try:
        hour, minute = map(int, value.strip().split(":"))
        # map(): Apply this function to every item in this list.
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
        raise ValueError
    except (ValueError, TypeError):
        raise ValueError("Use HH:MM 24-hour (e.g., 16:00)")


def _validate_schedule_type(value: str) -> ScheduleType:
    """Validate 'once' or 'weekly'"""
    value = _require_non_empty_text(value, "Schedule type").lower()
    if value == ScheduleType.ONCE.value:
        return ScheduleType.ONCE
    if value == ScheduleType.WEEKLY.value:
        return ScheduleType.WEEKLY
    raise ValueError("Must be 'once' or 'weekly'")


def _parse_days_input(value: str) -> list[int]:
    """Parse CLI comma-separated days into normalized day numbers."""
    try:
        days = [int(d.strip()) for d in value.split(",")]
        normalized_days = _normalize_days_list(days)
        if normalized_days is None:
            raise ValueError("At least one day is required")
        return normalized_days
    except ValueError as e:
        if "must be 1-7" in str(e):
            raise
        raise ValueError("Use comma-separated numbers (e.g., 1,3,5)")


def _parse_command_input(value: str) -> str:
    """Validate CLI command text and return the cleaned raw command."""
    _normalize_command_input(value)
    return _normalize_command_text(value)

def create_job(data: AddJobInput) -> Job:
    if _count_jobs() >= APP_CONFIG.max_jobs:
        raise ValueError("Maximum of 100 jobs reached")

    _validate_unique_job_name(data.name)
    job = _build_job(data)
    _schedule_single_job(job)
    return _insert_job(job)


def get_jobs() -> list[Job]:
    """Retrieve all jobs."""
    return _fetch_jobs()


def remove_job(identifier: str) -> bool:
    """
    Flow:
        remove -> remove_jobs
        remove_job
            -> _resolve_job_identifier
            -> _remove_job_from_db
    """
    job = _resolve_job_identifier(identifier)
    if not job:
        raise ValueError(f"Job '{identifier}' not found")
    
    job_id = job.id
    if job_id is None:
        raise ValueError(f"Job '{identifier}' not found")

    try:
        scheduler.remove_job(job_id)
    except JobLookupError as e:
        logger.warning(f"Job {job_id} not in scheduler: {e}")

    removed = _remove_job_from_db(job_id)
    if removed:
        logger.info(f"Job '{job.name}' ({_format_job_id(job_id)}) removed")
    
    return removed


def remove_jobs(identifiers: list[str]) -> list[Job]:
    jobs = [_resolve_job_identifier(identifier) for identifier in identifiers]
    removed_jobs: list[Job] = []
    for job in jobs:
        job_id = job.id or job.name
        if remove_job(job_id):
            removed_jobs.append(job)
    return removed_jobs


def resume_job(identifier: str) -> Job:
    """
    Flow:
        resume -> resume_jobs
        resume_job
            -> _resolve_job_identifier
            -> scheduler.resume_job
    """
    job = _resolve_job_identifier(identifier)
    if not job:
        raise ValueError(f"Job '{identifier}' not found")
    
    if job.status is JobStatus.ACTIVE:
        raise ValueError(f"Job '{job.name}' is already active")
    
    job_id = job.id
    if job_id is None:
        raise ValueError(f"Job '{job.name}' has no ID")

    # Resume in scheduler when this process owns in-memory jobs.
    try:
        if scheduler.get_job(job_id) is None:
            if scheduler.running:
                _schedule_single_job(job)
        else:
            scheduler.resume_job(job_id)
    except JobLookupError:
        pass
    except Exception as e:
        raise RuntimeError(f"Failed to resume: {e}")
    
    # Update status in database
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (JobStatus.ACTIVE.value, job_id))
    
    logger.info(f"Job '{job.name}' ({_format_job_id(job_id)}) resumed")
    return job


def resume_jobs(identifiers: list[str]) -> list[Job]:
    jobs = [_resolve_job_identifier(identifier) for identifier in identifiers]
    return [resume_job(job.id or job.name) for job in jobs]
    


def run_scheduler_foreground() -> None:
    existing_pid = _get_active_scheduler_pid()
    if existing_pid is not None:
        raise RuntimeError(f"Scheduler is already running (PID {existing_pid})")

    stop_event = threading.Event()

    def _handle_shutdown_signal(signum: int, frame: Any) -> None:
        stop_event.set()
        logger.info(f"Received signal {signum}, shutting down scheduler")

    previous_sigint = signal.getsignal(signal.SIGINT)
    previous_sigterm = signal.getsignal(signal.SIGTERM)

    try:
        signal.signal(signal.SIGINT, _handle_shutdown_signal)
        signal.signal(signal.SIGTERM, _handle_shutdown_signal)
        _write_pid_file(os.getpid())

        if not scheduler.running:
            scheduler.start()
            logger.info("Scheduler daemon started")
        else:
            logger.info("Scheduler already running")

        _load_jobs_from_database()

        while not stop_event.is_set():
            time.sleep(1)
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)

        if scheduler.running:
            logger.info("Stopping scheduler...")
            scheduler.shutdown(wait=True)
            logger.info("Scheduler stopped")

        _remove_pid_file()

def start_scheduler(foreground: bool = False) -> str:
    return _start_scheduler(
        foreground=foreground,
        run_foreground=run_scheduler_foreground,
    )


def stop_scheduler() -> bool:
    """
    Flow:
        stop -> stop_scheduler
        stop_scheduler
            -> stop_scheduler_process
    """
    return _stop_scheduler()


def pause_job(identifier: str) -> Job:
    """
    Flow:
        pause -> pause_jobs
        pause_job
            -> _resolve_job_identifier
            -> scheduler.pause_job
    """
    job = _resolve_job_identifier(identifier)
    
    if job.status is JobStatus.PAUSED:
        raise ValueError(f"Job '{job.name}' is already paused")
    
    job_id = job.id
    if job_id is None:
        raise ValueError(f"Job '{job.name}' has no ID")
    
    try:
        if scheduler.get_job(job_id) is not None:
            scheduler.pause_job(job_id)
    except JobLookupError:
        pass
    except Exception as e:
        raise RuntimeError(f"Failed to pause: {e}")
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (JobStatus.PAUSED.value, job_id))
    
    logger.info(f"Job '{job.name}' ({_format_job_id(job_id)}) paused")
    return job


def pause_jobs(identifiers: list[str]) -> list[Job]:
    jobs = [_resolve_job_identifier(identifier) for identifier in identifiers]
    return [pause_job(job.id or job.name) for job in jobs]

# ============================================
# CLI - Thin wrapper around orchestration
# ============================================

# CLI input/output: input str from typer, echo str to user. 
# str only at boundary
 
app = typer.Typer(
    name="scheduler",
    help="Cross-platform job scheduler",
    )

@app.callback()
def init():
    file_log = _setup_env()
    _setup_logger(file_log)
    _init_db()

# CORE retry engine
"""
Not core:

anything touching external libraries, frameworks database drivers, schedulers, CLI toolkits, or network clients, it is usually not core.
core should survive framework replacement
"""

def _prompt_until_valid[T](
    prompt_text: str, 
    op: Callable[[str], T],
    max_attempts: int = 3,
    error_prefix: str = "❌"
) -> T:
    """
    Generic = only when multiple return types are required.
    
    Prompt user repeatedly until valid input or max attempts reached.
    
    Args:
        prompt_text: What to ask
        validator: Function that returns parsed value or raises ValueError
        max_attempts: Maximum tries before giving up
        error_prefix: Prefix for error messages
    
    Returns:
        Validated and parsed value
    
    Raises:
        typer.Exit: If max attempts exceeded
    """

        
    for attempt in range(1, max_attempts + 1):
        try:
            value = input(prompt_text)
            return op(value)
            
        except ValueError as e:
            remaining = max_attempts - attempt
            
            if remaining > 0:
                typer.echo(f"{error_prefix} {e} ({remaining} attempt(s) left)", err=True)
            else:
                typer.echo(f"{error_prefix} Too many invalid attempts. Exiting.", err=True)
                raise typer.Exit(1)
            
        
        except (EOFError, KeyboardInterrupt):
            typer.echo("\n✗ Cancelled", err=True)
            raise typer.Exit(1)
    
    # Should never reach here
    raise typer.Exit(1)

def _prompt_time_value() -> str:
    """Prompt for a time in either 12-hour or 24-hour format."""
    use_12h = typer.confirm("Use 12-hour format?", default=False)
    if use_12h:
        return _prompt_until_valid(
            "Time (HH:MM AM/PM): ",
            _validate_time_12h,
            error_prefix="Use HH:MM AM/PM (e.g., 03:00 PM)"
        )

    return _prompt_until_valid(
        "Time (HH:MM 24-hour): ",
        _validate_time_24h,
        error_prefix="Use HH:MM 24-hour (e.g., 15:00)"
    )

def _parse_weekly_time_input(value: str) -> str:
    """Accept either 24-hour or 12-hour CLI time for weekly jobs."""
    try:
        return _validate_time_24h(value)
    except ValueError:
        return _validate_time_12h(value)

def _parse_once_datetime_input(value: str) -> str:
    """Validate a one-time CLI datetime and normalize it."""
    try:
        return datetime.fromisoformat(value.strip()).isoformat()
    except ValueError as e:
        raise ValueError("Use ISO datetime (e.g., 2026-04-19T13:00)") from e
        # ISO = International Organization for Standardization

def collect_job_input_interactively() -> AddJobInput:
    """Collect add command input interactively."""
    name = _prompt_until_valid("Job name: ", _validate_unique_job_name, error_prefix="Invalid name")
    command = _prompt_until_valid(
        "Command: ",
        _parse_command_input,
        max_attempts=3,
        error_prefix="Invalid command"
    )
    schedule_type = _prompt_until_valid(
        "Type (once/weekly): ",
        _validate_schedule_type,
        error_prefix="Must be 'once' or 'weekly'"
    )

    if schedule_type is ScheduleType.WEEKLY:
        parsed_days = _prompt_until_valid(
            "Days (comma-separated, 1-7): ",
            _parse_days_input,
            error_prefix="Use numbers 1-7 separated by commas"
        )
        scheduled_time = _prompt_time_value()
        return AddJobInput(
            name=name,
            command=command,
            schedule_type=schedule_type,
            days_of_week=parsed_days,
            scheduled_time=scheduled_time
        )

    date_str = _prompt_until_valid(
        "Date (YYYY-MM-DD): ",
        _validate_date,
        error_prefix="Use YYYY-MM-DD format"
    )
    time_str = _prompt_time_value()
    return AddJobInput(
        name=name,
        command=command,
        schedule_type=schedule_type,
        scheduled_time=f"{date_str}T{time_str}"
    )

def collect_job_input_from_cli(
    name: str | None,
    command: str | None,
    schedule_type: str | None,
    days_list: str | None,
    scheduled_time: str | None
) -> AddJobInput:
    """Collect add command input from direct CLI options."""
    if name is None or command is None or schedule_type is None:
        raise ValueError("Missing required fields")

    validated_name = _validate_unique_job_name(name)
    validated_command = _normalize_command_text(command)
    normalized_type = _validate_schedule_type(schedule_type)

    if normalized_type is ScheduleType.WEEKLY:
        if days_list is None or scheduled_time is None:
            raise ValueError("Weekly jobs require --days and --time")

        return AddJobInput(
            name=validated_name,
            command=validated_command,
            schedule_type=normalized_type,
            days_of_week=_parse_days_input(days_list),
            scheduled_time=_parse_weekly_time_input(scheduled_time)
        )

    if scheduled_time is None:
        raise ValueError("One-time jobs require --time")

    return AddJobInput(
        name=validated_name,
        command=validated_command,
        schedule_type=normalized_type,
        scheduled_time=_parse_once_datetime_input(scheduled_time)
    )

@app.command()
def add(
    name: str | None = typer.Option(None, "--name", "-n", help="Job name"),
    command: str | None = typer.Option(None, "--command", "-c", help="Command to execute"),
    schedule_type: str | None = typer.Option(None, "--type", "-t", help="'once' or 'weekly'"),
    days_list: str | None = typer.Option(None, "--days", "-d", help="Comma-separated days: 1,3,5"),
    scheduled_time: str | None = typer.Option(None, "--time", help="HH:MM or ISO datetime"),
    interactive: bool = typer.Option(False, "--interactive", "-i", help="Interactive mode")
):
    """Add a new scheduled job"""
    try:
        if interactive:
            data = collect_job_input_interactively()
        else:
            data = collect_job_input_from_cli(
                name=name,
                command=command,
                schedule_type=schedule_type,
                days_list=days_list,
                scheduled_time=scheduled_time
            )
        
        job = create_job(data)
        display_id = _format_job_id(job.id)
        local_time = job.next_runtime.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")
        
        typer.echo(f"\n✓ Job created: {display_id}")
        typer.echo(f"  Next run: {local_time}")
        
    except ValueError as e:
        typer.echo(f"✗ {e}", err=True)
        raise typer.Exit(1)

@app.command("list")
def list_command(verbose: bool = typer.Option(False, "--verbose", "-v")):
    """List all scheduled jobs"""

    jobs = get_jobs()
    
    if not jobs:
        typer.echo("No jobs scheduled")
        return
    
    for job in jobs:
        if verbose:
            typer.echo(f"\nID: {job.id}")
            typer.echo(f"  Name: {job.name}")
            typer.echo(f"  Command: {job.command}")
            typer.echo(f"  Schedule: {job.schedule_type}")

            if job.days_of_week:
                days_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                days_str = ", ".join(days_names[d-1] for d in job.days_of_week)
                typer.echo(f"  Days: {days_str}")
            typer.echo(f"  Time: {_format_scheduled_time(job)}")
            typer.echo(f"  Next run: {job.next_runtime.astimezone(LOCAL_TZ)}")
            typer.echo(f"  Status: {job.status}")
        else:
             
            short_id = _format_job_id(job.id)
            local_time = job.next_runtime.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")
            typer.echo(f"[{short_id}] {_status_label(job.status)} | {job.name} → {local_time}")


@app.command()
def start(
    foreground: bool = typer.Option(False, "--foreground", "-f", help="Run scheduler in foreground")
):
    """Start the scheduler daemon"""
    try:
        if foreground:
            if os.name == 'nt':
                typer.echo("Starting scheduler (Windows mode)...")
            else:
                typer.echo("Starting scheduler (Ctrl+C to stop)...")

        message = start_scheduler(foreground=foreground)
        if not foreground:
            typer.echo(f"✓ {message}")
    except RuntimeError as e:
        typer.echo(f"✗ {e}", err=True)
        raise typer.Exit(1)

    
@app.command()
def stop():
    """Stop the scheduler daemon"""
    try:
        stopped = stop_scheduler()
        if stopped:
            typer.echo("✓ Scheduler stopped")
        else:
            typer.echo("Scheduler already stopped")
    except Exception as e:
        typer.echo(f"✗ Error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def status():
    """Show scheduler process status"""
    try:
        scheduler_status = get_scheduler_status()

        if not scheduler_status.is_running:
            typer.echo("Scheduler status: stopped")
        else:
            typer.echo(f"Scheduler status: running (PID {scheduler_status.pid})")
            typer.echo(f"Process: {scheduler_status.process_status} | started {scheduler_status.started_at}")

        typer.echo(
            f"Jobs: {scheduler_status.total_jobs} total | "
            f"{scheduler_status.active_jobs} active | "
            f"{scheduler_status.paused_jobs} paused"
        )
        typer.echo(f"PID file: {scheduler_status.pid_file}")
    except Exception as e:
        typer.echo(f"✗ Error: {e}", err=True)
        raise typer.Exit(1)
    

@app.command()
def pause(
    identifiers: list[str] = typer.Argument(..., help="One or more job IDs, prefixes, or exact names")
):
    """Pause a scheduled job"""
    try:
        jobs = pause_jobs(identifiers)
        for job in jobs:
            typer.echo(f"⏸ Job '{job.name}' ({_format_job_id(job.id)}) paused")
        
    except ValueError as e:
        typer.echo(f"✗ {e}", err=True)
        raise typer.Exit(code=1)
    except RuntimeError as e:
        typer.echo(f"✗ {e}", err=True)
        raise typer.Exit(code=1)



@app.command()
def remove(
    identifiers: list[str] = typer.Argument(..., help="One or more job IDs, prefixes, or exact names"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation")
):
    """Remove a scheduled job"""
    try:
        jobs = [_resolve_job_identifier(identifier) for identifier in identifiers]

        if not force:
            job_labels = ", ".join(f"{job.name} ({_format_job_id(job.id)})" for job in jobs)
            if not typer.confirm(f"Remove {len(jobs)} job(s): {job_labels}?"):
                typer.echo("Cancelled")
                raise typer.Exit(0)

        removed_jobs = remove_jobs(identifiers)
        if not removed_jobs:
            typer.echo("✗ Failed to remove jobs", err=True)
            raise typer.Exit(1)

        for job in removed_jobs:
            typer.echo(f"✓ Job '{job.name}' removed")
            
    except ValueError as e:
        typer.echo(f"✗ {e}", err=True)
        raise typer.Exit(1)


@app.command()
def resume(
    identifiers: list[str] = typer.Argument(..., help="One or more job IDs, prefixes, or exact names")
):
    """Resume a paused job"""
    try:
        jobs = resume_jobs(identifiers)
        for job in jobs:
            typer.echo(f"▶ Job '{job.name}' ({_format_job_id(job.id)}) resumed")
    
    except ValueError as e:
        typer.echo(f"✗ {e}", err=True)
        raise typer.Exit(1)
    except RuntimeError as e:
        typer.echo(f"✗ {e}", err=True)
        raise typer.Exit(1)


@app.command()
def install(
    system: bool = typer.Option(False, "--system", "-s", help="System-wide install (requires sudo on Linux)")
):
    """Install scheduler as background service"""
    try:
        platform = _detect_platform()
        
        if platform == "windows" and system:
            typer.echo("⚠️  --system flag ignored on Windows")
        
        msg, steps = install_scheduler_service(system)
        typer.echo(msg)
        
        if steps:
            typer.echo("\nNext steps:")
            for step in steps:
                typer.echo(f"  {step}")
                
    except Exception as e:
        typer.echo(f"✗ Installation failed: {e}", err=True)
        raise typer.Exit(1)

# ============================================
# ENTRY
# ============================================

if __name__ == "__main__":
    
    app()


"""
python3 scheduler_3/scheduler.py start (default: Background)
python3 scheduler_3/scheduler.py start --foreground
python3 scheduler_3/scheduler.py status
python3 scheduler_3/scheduler.py pause job1 job2
python3 scheduler_3/scheduler.py resume job1 job2
python3 scheduler_3/scheduler.py stop

"""
