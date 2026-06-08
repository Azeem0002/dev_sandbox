#!/usr/bin/env python3

"""
sudo cp scheduler.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable scheduler
sudo systemctl start scheduler
"""
from zoneinfo import ZoneInfo
from loguru import logger
from datetime import datetime
from enum import StrEnum
import os
import threading
import typer
import time
import shlex
import shutil
import uuid
import signal
import subprocess
from typing import Any, Callable


# APSCHEDULER
from apscheduler.schedulers.background import BackgroundScheduler  # The alarm clock/timer engine: runs jobs in background thread
from apscheduler.triggers.date import DateTrigger                  # "Run once at specific time"
from apscheduler.triggers.cron import CronTrigger                  # "Run every Monday at 9": recurring schedule
from apscheduler.jobstores.base import JobLookupError               # "Job not found" error: the alarm doesn't exist

# ============================================
# CONFIG
# ============================================

from pydantic import BaseModel, ConfigDict, field_validator, model_validator
try:
    from .database_adapter import (
        init_db,
        insert_job,
        fetch_jobs,
        remove_job_from_db,
        count_jobs,
        count_jobs_by_status,
        update_job_status,
    )
    from .job_models import (
        Job,
        JobStatus,
        ScheduleType,
        normalize_job_name,
        parse_scheduled_time_from_storage,
        format_job_id,
    )
    from .lifecycle_models import SchedulerStatus
    from .platform_adapter import detect_platform
    from .process_adapter import (
        get_active_process_pid,
        get_pid_file_path,
        remove_pid_file,
        spawn_detached_process,
        stop_process,
        write_pid_file,
    )
    from .runtime_support import get_local_timezone, is_dev_env, setup_environment, setup_logger
    from .service_adapter import install_service
except ImportError:
    from database_adapter import (
        init_db,
        insert_job,
        fetch_jobs,
        remove_job_from_db,
        count_jobs,
        count_jobs_by_status,
        update_job_status,
    )
    from job_models import (
        Job,
        JobStatus,
        ScheduleType,
        normalize_job_name,
        parse_scheduled_time_from_storage,
        format_job_id,
    )
    from lifecycle_models import SchedulerStatus
    from platform_adapter import detect_platform
    from process_adapter import (
        get_active_process_pid,
        get_pid_file_path, 
        remove_pid_file,
        spawn_detached_process,
        stop_process,
        write_pid_file,
    )
    from runtime_support import get_local_timezone, is_dev_env, setup_environment, setup_logger
    from service_adapter import install_service

class AppConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    app_name: str = "scheduler"
    app_author: str = "Al-Azeem"
    storage_timezone: str = "UTC" # for database 
    max_jobs: int = 100


APP_CONFIG = AppConfig()
STORAGE_TZ = ZoneInfo(APP_CONFIG.storage_timezone)
LOCAL_TZ = get_local_timezone()

scheduler = BackgroundScheduler(timezone=LOCAL_TZ)

# ============================================
# BOUNDARY INPUT MODELS
# ============================================
#
# `Job`, `ScheduleType`, and `JobStatus` were extracted to `job_models.py`
# because both orchestration and persistence need the same shared meaning.

class RunMode(StrEnum):
    FOREGROUND = "foreground"
    BACKGROUND = "background"


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
        """Adapt name for model."""
        return normalize_job_name(value)

    @field_validator("command", mode="before") 
    # field_validator must match the exact field name in your model
    @classmethod
    def _adapt_command_for_model(cls, value: Any) -> str:
        # Keep 'type: Any' for mode="before". data could be any type
        """Adapt command for model."""
        return _parse_command_input(value)

    @field_validator("schedule_type", mode="before") # mode="before": Before Pydantic type conversion
    @classmethod
    def _adapt_schedule_type_for_model(cls, value: Any) -> ScheduleType:
        # Any acknowledges "we don't know what we'll get yet" before Pydantic coerces to enum.
        """Adapt schedule type for model."""
        if not isinstance(value, str): # for validating type directly/correctly
            raise TypeError("Schedule type must be text")
        return _validate_schedule_type(value)

    @field_validator("days_of_week")
    @classmethod
    def _adapt_days_for_model(cls, value: list[int] | None) -> list[int] | None:
        """Adapt days for model."""
        return _normalize_days_list(value)

    @field_validator("scheduled_time")
    @classmethod
    def _adapt_scheduled_time_for_model(cls, value: str | None) -> str | None:
        """Adapt scheduled time for model."""
        if value is None:
            return None
        return value.strip()

    @model_validator(mode="after") # model_validator: checking multiple fields at once. comes last after all field validations
    # mode="after": After pydantic type conversion 
    def _validate_schedule_shape(self) -> "AddJobInput": #self: after the instance exists
        """Validate schedule shape."""
        if self.schedule_type == ScheduleType.ONCE:  # checks if user is using the schedule type once.
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

# ============================================
# RESPONSIBILITIES (pure core logic)
# ============================================

# Display-only formatter.
# Storage formatting lives in `job_models.py` so the database adapter can use it too.

def _format_scheduled_time(job: Job) -> str:
    """
    DISPLAY FORMATTER: datetime → UI human-readable string
    """
    if job.scheduled_time is None:
        return "-"
    if job.schedule_type == ScheduleType.WEEKLY:
        return job.scheduled_time.astimezone(LOCAL_TZ).strftime("%H:%M %Z")  # strftime("%H:%M"): convert datetime → "14:30"
    return job.scheduled_time.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M %Z") # .astimezone(): converts datetime to the current timezone

def _create_trigger(
    schedule_type: ScheduleType,
    days_of_week: list[int] | None,
    scheduled_time: datetime | None
):
    """
    Create APScheduler trigger for single or multiple days.
    
    Args:
        days: Single day (as list with one item) or multiple days
              Example: [3] for Wednesday, [1,3,5] for Mon/Wed/Fri
    """
    if schedule_type == ScheduleType.ONCE:
        if not scheduled_time:
            raise ValueError("Time required for 'once'")

        target = scheduled_time.astimezone(LOCAL_TZ)
        if target <= datetime.now(LOCAL_TZ):
            raise ValueError("Time must be in future")

        return DateTrigger(run_date=target, timezone=LOCAL_TZ)

    if schedule_type == ScheduleType.WEEKLY:
        if not days_of_week or not scheduled_time:
            raise ValueError("Weekly requires day(s) and time")

        # Validate all days
        for d in days_of_week:
            if not (1 <= d <= 7): # day must be between 1-7
                # day is greater than or equal to 1 and less than or equal to 7
                raise ValueError(f"Invalid day: {d}. Must be 1-7")

        local_time = scheduled_time.astimezone(LOCAL_TZ)
        hour = local_time.hour # built in attribute of datetime object e.g dt = datetime(2026, 5, 1, 14(h), 30(m))
        minute = local_time.minute
        days_map = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

        # Convert to cron string: "mon,wed,fri"
        cron_days = ",".join(days_map[d-1] for d in days_of_week) #  # Look up in list
        # days_map[d-1]: d=1 → days_map[0] → "mon"

        return CronTrigger(
            day_of_week=cron_days,
            hour=hour,
            minute=minute,
            timezone=LOCAL_TZ
        )
    
    raise ValueError(f"Invalid schedule_type: {schedule_type}")

def _get_next_run(trigger, schedule_type: ScheduleType):
    """Ask APScheduler instead of guessing"""

    if schedule_type == ScheduleType.ONCE:
        # trigger is always either DateTrigger or CronTrigger
        next_run = trigger.run_date  # .run_date: → assumes trigger is DateTrigger: 'ONCE'
    else:
        next_run = trigger.get_next_fire_time(None, datetime.now(LOCAL_TZ)) # → assumes CronTrigger: 'WEEKLY'

    return next_run.astimezone(STORAGE_TZ)


def _execute_job_commands(commands: list[str]) -> None:
    """Execute a scheduled job with proper logging"""
    
    returncode = -1 # -1: not executed yet / failed by default. Convention for "unknown/error"
    logger.info(f"STARTING: {commands[:50]}...")  # → first 50 characters/items of the list

    try:
        result = subprocess.run(
            commands,
            capture_output=True,
            text=True,
            timeout=300,
            shell=False,
            start_new_session=True
        )
        returncode = result.returncode  # → actual exit code from subprocess

        if returncode == 0:
            logger.info(f"SUCCESS: {result.stdout.strip()}")
        else:
            logger.error(f"FAILED ({returncode}): {result.stderr.strip()}")

    except subprocess.TimeoutExpired:
        logger.error("TIMEOUT after 300s")
    except FileNotFoundError:
        logger.error(f"NOT FOUND: {commands[0] if commands else 'unknown'}")
    except Exception as e:
        logger.error(f"ERROR: {type(e).__name__}: {e}")
    finally:
        logger.info(f"COMPLETED: exit {returncode}")

def _build_job(data: AddJobInput) -> Job:
    """Transform input into complete Job object"""
    schedule_type = data.schedule_type
    scheduled_time = parse_scheduled_time_from_storage(schedule_type, data.scheduled_time)
    command_parts = _normalize_command(data.command)[1]

    trigger = _create_trigger(
        schedule_type,
        data.days_of_week,
        scheduled_time
    )

    next_run = _get_next_run(trigger, schedule_type)

    return Job(
        id=str(uuid.uuid4()), # Universally Unique Identifier v4. Generates random 128-bit identifiers. 
        # → UUID('a1b2c3d4-e5f6-7890-abcd-ef1234567890'). str(...) → 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'
        # Origin: Built-in Python uuid module. Guarantees globally unique IDs without a central authority.
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

    if job.status != JobStatus.ACTIVE:
        return
    
    # Attributes: Data attached to the object class. Adjective: describes the thing
    trigger = _create_trigger(
        job.schedule_type,
        job.days_of_week,
        job.scheduled_time
    )
    scheduler.add_job( #.add_job: is a method of BackgroundScheduler
        _execute_job_commands, # Function to call
        trigger=trigger, # When to call it
        id=job.id,  # Unique ID for this job
        name=job.name, # Human-readable name
        kwargs={"commands": job.command}, # Arguments passed to function
        replace_existing=True,  # Overwrite if same ID exists
        coalesce=True,  # Skip missed runs
        max_instances=1,  # Only one copy runs at a time
    )    

def _resolve_job_identifier(identifier: str) -> Job:
    """
    Resolve: figure out user input (full id, short id, or name) → full job_id
    """
    token = identifier.strip()
    jobs = fetch_jobs()

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
    """Find job by name."""
    normalized_name = name.strip().casefold() # Aggressive lowercase for case-insensitive comparison.
    for job in fetch_jobs():
        if job.name.strip().casefold() == normalized_name:
            return job
    return None

def _status_label(status: JobStatus) -> str:
    """Status label."""
    if status is JobStatus.PAUSED:
        return "⏸ paused"
    return "▶ active"

def _load_jobs_from_database() -> int:
    """Restore all active jobs from database on startup"""

    jobs = fetch_jobs()
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
                display_id = format_job_id(job.id)

                # ✅ Show job details
                next_run = job.next_runtime.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")
                logger.info(f"  ✓ [{display_id}] {job.name} → {next_run}")
                
            except ValueError as e:
                display_id = format_job_id(job.id)
                logger.error(f"  ✗ [{display_id}] Invalid config: {e}")
            except (RuntimeError, OSError) as e:
                display_id = format_job_id(job.id)
                logger.error(f"  ✗ [{display_id}] Failed to load  job: {type(e).__name__}")
        else:
            display_id = format_job_id(job.id)
            logger.debug(f"  ⏸ [{display_id}] {job.name} (paused)")

    return loaded

def _normalize_command(value: Any) -> tuple[str, list[str]]:
    """Normalize command."""
    if not isinstance(value, str):
        raise ValueError("Command must be text")
    cleaned = value.strip()
    parts= shlex.split(value)
    if not cleaned:
        raise ValueError("Command cannot be empty")

    cleaned_parts = [part.strip() for part in parts if part.strip()]
    if not cleaned_parts:
        raise ValueError("Command cannot be empty")

    forbidden = [";", "&", "|", "\n", "\r", "`", "$(", ">", "<"]
    for part in cleaned_parts:
        for token in forbidden:
            if token in part:
                raise ValueError(f"Unsafe pattern: {token}")

    executable = cleaned_parts[0]
    if not any(char.isalnum() for char in executable):
        raise ValueError("Command executable is invalid")
    if "/" in executable or "\\" in executable:
        if not os.path.exists(executable):
            raise ValueError(f"Command executable '{executable}' was not found")
    elif shutil.which(executable) is None:
        raise ValueError(f"Command executable '{executable}' was not found")

    return cleaned, cleaned_parts


def _parse_command_input(value: Any) -> str:
    """Validate CLI command text and return the normalized command string."""
    return _normalize_command(value)[0]

def _normalize_days_list(value: list[int] | None) -> list[int] | None:
    """Normalize days list."""
    if value is None:
        return None

    normalized = sorted(set(value))
    for day in normalized:
        if not (1 <= day <= 7):
            raise ValueError(f"Day {day} must be 1-7")
    return normalized

def _validate_unique_job_name(value: str) -> str:
    """Validate unique job name."""
    cleaned = normalize_job_name(value)
    existing = _find_job_by_name(cleaned)
    if existing is not None:
        raise ValueError(
            f"Job name '{cleaned}' already exists ({format_job_id(existing.id)}). Use a different name."
        )
    return cleaned

# ===== VALIDATORS (Pure functions, no I/O) =====

def _validate_date(value: str) -> str:
    """Parse flexible date formats, return YYYY-MM-DD"""
    formats = ["%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"]
    for fmt in formats:
        try:
            parsed = datetime.strptime(value.strip(), fmt) # strptime()'parsing': string → datetime. for reading input str
            return parsed.strftime("%Y-%m-%d") # strftime()'formatting: datetime → string. for formatting output to str
        except ValueError:
            continue
    raise ValueError("Use YYYY-MM-DD (e.g., 2026-04-18)")


def _validate_time_12h(value: str) -> str:
    """Parse 12-hour time, return HH:MM (24-hour)"""
    try:
        parsed = datetime.strptime(value.strip(), "%I:%M %p") # %I: parses 12h clock "03:00 PM" → datetime object
        return parsed.strftime("%H:%M") # %H: parses 24h clock. %H + %p is invalid combination.
    except ValueError:
        raise ValueError("Use HH:MM AM/PM (e.g., 03:00 PM)")


def _validate_time_24h(value: str) -> str:
    """Parse 24-hour time, return HH:MM"""
    try:
        parsed = datetime.strptime(value.strip(), "%H:%M")
        return parsed.strftime("%H:%M")
    except ValueError:
        raise ValueError("Use HH:MM 24-hour (e.g., 16:00)")


def _validate_schedule_type(value: str) -> ScheduleType:
    """Validate 'once' or 'weekly'"""
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned:
        raise ValueError("Schedule type cannot be empty")
    value_lower = cleaned.lower()
    if value_lower == ScheduleType.ONCE.value:
        return ScheduleType.ONCE
    if value_lower == ScheduleType.WEEKLY.value:
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


def _format_next_run_local(job: Job) -> str:
    """Format next run local."""
    return job.next_runtime.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M %Z")


def _format_next_run_utc(job: Job) -> str:
    """Format next run utc."""
    return job.next_runtime.astimezone(STORAGE_TZ).strftime("%Y-%m-%d %H:%M %Z")


def _format_started_at(value: datetime | None) -> str:
    """Format started at."""
    if value is None:
        return "-"
    return value.strftime("%Y-%m-%d %H:%M:%S %Z")

# ============================================
# CLI - Thin wrapper around orchestration
# ============================================

try:
    from .application import (
        create_job,
        get_jobs,
        get_scheduler_status,
        pause_jobs,
        remove_jobs,
        resume_jobs,
        start_scheduler,
        stop_scheduler,
    )
except ImportError:
    from application import (
        create_job,
        get_jobs,
        get_scheduler_status,
        pause_jobs,
        remove_jobs,
        resume_jobs,
        start_scheduler,
        stop_scheduler,
    )

# CLI input/output: input str from typer, echo str to user. 
# str only at boundary
 
app = typer.Typer(
    name="scheduler",
    help="Cross-platform job scheduler",
    )

@app.callback()
def init():
    # Boundary setup only. This is not business logic.
    # We prepare logging and ensure the DB schema exists before any CLI command runs.
    """Initialize the runtime environment for this module."""
    file_log = setup_environment()
    setup_logger(file_log)
    init_db()

"""
Not core:

anything touching external libraries, frameworks database drivers, schedulers, CLI toolkits, or network clients, it is usually not core.
core should survive framework replacement
"""

def _prompt_until_valid[T](
    prompt_text: str, 
    op: Callable[[str], T],
    max_attempts: int = 3,
    error_prefix: str | None = None
) -> T:
    """
    Generic = only when multiple return types are required.
    
    Prompt user repeatedly until valid input or max attempts reached.
    
    Args:
        prompt_text: What to ask
        op: Function that returns parsed value or raises ValueError
        max_attempts: Maximum tries before giving up
        error_prefix: Optional context label for error messages
    
    Returns:
        Validated and parsed value
    
    Raises:
        typer.Exit: If max attempts exceeded
    """

    for attempt in range(1, max_attempts + 1):
    
        try:
            value = input(f"{prompt_text.rstrip(': ')}: ")
            return op(value)
            
        except ValueError as e:
            remaining = max_attempts - attempt
            detail = str(e).strip()
            if error_prefix and detail and detail != error_prefix:
                message = f"{error_prefix}: {detail}"
            else:
                message = detail or error_prefix or "Invalid input"
            
            if remaining > 0:
                typer.echo(f"{message} ({remaining} attempt(s) left)", err=True)
            else:
                typer.echo(f"{message}. Too many invalid attempts. Exiting...", err=True)
                raise typer.Exit(1)
            
        
        except (EOFError, KeyboardInterrupt): # EOFerror: End Of File Error: “Expected input, but got nothing”.User sends EOF (Ctrl+D / Ctrl+Z)
            # Raised when user interrupts execution: ctrl + c
            typer.echo("\n✗ Cancelled", err=True)
            raise typer.Exit(code=1)
    
    # Should never reach here
    raise typer.Exit(1)

def _prompt_time_value() -> str:
    """Prompt for a time in either 12-hour or 24-hour format."""
    use_12h = typer.confirm("Use 12-hour format?", default=False)
    if use_12h:
        return _prompt_until_valid(
            "Time (HH:MM AM/PM)",
            _validate_time_12h,
            error_prefix=None
        )

    return _prompt_until_valid(
        "Time (HH:MM 24-hour)",
        _validate_time_24h,
        error_prefix=None
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
        return datetime.fromisoformat(value.strip()).isoformat() # Parse string → datetime, then back to string. This normalizes formats.
    except ValueError as e:
        raise ValueError("Use ISO datetime (e.g., 2026-04-19T13:00)") from e
        # ISO = International Organization for Standardization

def collect_job_input_interactively() -> AddJobInput:
    """Collect add command input interactively."""
    name = _prompt_until_valid(
        "Job name", 
        _validate_unique_job_name, 
        error_prefix="Invalid name"
    )
    
    command = _prompt_until_valid(
        "Command",
        _parse_command_input,
        max_attempts=3,
        error_prefix="Invalid command"
    )
    schedule_type = _prompt_until_valid(
        "Type (once/weekly)",
        _validate_schedule_type,
        error_prefix=None
    )

    if schedule_type == ScheduleType.WEEKLY:
        parsed_days = _prompt_until_valid(
            "Days (comma-separated, 1-7)",
            _parse_days_input,
            error_prefix=None
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
        "Date (YYYY-MM-DD)",
        _validate_date,
        error_prefix=None
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
    validated_command = _normalize_command(command)[0]
    normalized_type = _validate_schedule_type(schedule_type)

    if normalized_type == ScheduleType.WEEKLY:
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
        display_id = format_job_id(job.id)
        local_time = job.next_runtime.astimezone(LOCAL_TZ).strftime("%d-%m-%Y %H:%M")
        
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

                # Translation: "For each day number in days_of_week, look up its name from the list."
                days_str = ", ".join(days_names[d-1] for d in job.days_of_week) # Convert numbers → names
                typer.echo(f"  Days: {days_str}")
            typer.echo(f"  Scheduled time (local): {_format_scheduled_time(job)}")
            typer.echo(f"  Next run (local): {_format_next_run_local(job)}")
            typer.echo(f"  Next run (UTC): {_format_next_run_utc(job)}")
            typer.echo(f"  Status: {job.status}")
        else:
             
            short_id = format_job_id(job.id)
            local_time = _format_next_run_local(job)
            typer.echo(f"[{short_id}] {_status_label(job.status)} | {job.name} → {local_time}")


@app.command()
def start(
    foreground: bool = typer.Option(False, "--foreground", "-f", help="Run scheduler in foreground")
):
    """Start the scheduler daemon"""
    
    try:
        mode = RunMode.FOREGROUND if foreground else RunMode.BACKGROUND

        message = start_scheduler(foreground) # Always define variables before branches, not inside them

        if foreground:
            if os.name == 'nt':
                typer.echo("Starting scheduler (Windows mode)...")
            else:
                typer.echo("Starting scheduler (Ctrl+C to stop)...")
        
        else:
            typer.echo(f"✓ {message}")
            scheduler_status = get_scheduler_status()
            typer.echo(
                f"Jobs: {scheduler_status.total_jobs} total | "
                f"{scheduler_status.active_jobs} active | "
                f"{scheduler_status.paused_jobs} paused"
                )
        
        return mode
    except (RuntimeError, OSError) as e:
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
        raise typer.Exit(code=1)


@app.command()
def status():
    """Show scheduler process status"""
    try:
        scheduler_status = get_scheduler_status()

        if not scheduler_status.is_running:
            typer.echo("Scheduler status: stopped")
        else:
            typer.echo(f"Scheduler status: running (PID {scheduler_status.pid})")
            typer.echo(
                f"Process: {scheduler_status.process_status} | "
                f"started {_format_started_at(scheduler_status.started_at)}"
            )

        typer.echo(
            f"Jobs: {scheduler_status.total_jobs} total | "
            f"{scheduler_status.active_jobs} active | "
            f"{scheduler_status.paused_jobs} paused"
        )
        if is_dev_env():
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
            typer.echo(f"⏸ Job '{job.name}' ({format_job_id(job.id)}) paused")
        
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
            job_labels = ", ".join(f"{job.name} ({format_job_id(job.id)})" for job in jobs)
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
            typer.echo(f"▶ Job '{job.name}' ({format_job_id(job.id)}) resumed")
    
    except ValueError as e:
        typer.echo(f"✗ {e}", err=True)
        raise typer.Exit(code=1)
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
        
        msg, steps = install_service(system=system)
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
