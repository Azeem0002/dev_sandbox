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
from dataclasses import dataclass
from datetime import datetime
from platformdirs import PlatformDirs
import os
import typer
import time
import sys
import uuid
import shlex
import json
import subprocess
from tenacity import retry, stop_after_attempt, wait_exponential
from typing import Callable, Literal, TypeVar


# APSCHEDULER
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.base import JobLookupError

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

    LOG_DIR= Path(dirs.user_log_dir)

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.debug(f"Failed to create directory")
        raise PermissionError(f"Failed to create directory") from e
    
    file_log= LOG_DIR / "scheduler.log"
    return file_log

def _setup_logger(file_log: Path)-> None:

    ENV= os.getenv("APP_ENV", "dev")
    logger.remove()
    
    if ENV== "prod":
        logger.add(
            sink=sys.stdout,
            level="INFO"
        )
    else:
        logger.add(
            sink= sys.stdout,
            level= "DEBUG",
            format= "<cyan>{time:YYYY-MM-DD HH:mm:ss}</cyan> | "
                    "{level: <8} | "
                    "{module}.{function}:{line} | "
                    "<level>{message}</level>",
            colorize=True,
            backtrace=True
        )
    logger.add(
        sink=file_log,
        level="DEBUG",
        format= "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {module}.{function}:{line} | {message}",
        rotation= "1 MB",
        retention= "3 days",
        compression="gz",
        enqueue=True,
        serialize= False,
        backtrace=False,
        diagnose=False, # diagnose=True can expose: variables in secrets, file paths, internal state
        catch=False,    
    )

# ============================================
# MODELS
# ============================================

# Object: An instance of a class, Noun: Name of thing
@dataclass 
class AddJobInput: #Job application form
    """User's request (raw input)"""
    name: str
    commands: list[str] # secure
    schedule_type: str  # "once" | "weekly"
    days_of_week: list[int] | None = None  # 1–7
    scheduled_time: str | None = None

@dataclass
class Job: # Employee record after hiring
    """Stored entity in database"""

    id: str | None          # Database primary key (None until saved)
    name: str                 # Human-readable label ("Daily Backup")
    commands: list[str]              # Shell command to execute
    schedule_type: str        # "once" or "weekly"
    days_of_week: list[int] | None   # 1=Monday..7=Sunday (only for weekly)
    scheduled_time: str | None      # "21:00" or "2026-04-14T15:30:00"
    next_runtime: datetime   # Pre-calculated UTC timestamp (core driver!)
    status: Literal["active", "paused"] = "active"    # "active" or "paused"
    # Literal: prevents invalid values):


# ============================================
# OS LAYER (I/O, no CLI output)
# ============================================

def _detect_platform() -> str:
    if os.name == "nt":  # Uses Task Scheduler
        return "windows"

    if sys.platform.startswith("linux"): # Uses systemd
    # os.name == "posix" would incorrectly assume macOS uses systemd. It doesn't.
        return "linux"

    if sys.platform == "darwin":  # Uses launched
        return "mac"

    return "unknown"

def _build_systemd_service() -> str:
    """Generate systemd service file content"""
    return f"""[Unit]
Description=Job Scheduler
After=network.target

[Service]
Type=simple
WorkingDirectory={Path(__file__).parent.resolve()}
ExecStart={sys.executable} {Path(__file__).resolve()} start
Restart=on-failure
RestartSec=10
MemoryMax=200M
CPUQuota=50%
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""


# ============================================
# RESPONSIBILITIES (pure core logic)
# ============================================

def _build_windows_task_command() -> list[str]:
    python_exe = sys.executable
    script_path = Path(__file__).resolve()

    return [
        "schtasks",
        "/create",
        "/tn", "Scheduler",
        "/tr", f'{python_exe} "{script_path}" start',
        "/sc", "onstart",
        "/rl", "highest",
        "/f"
    ]
    

# Core input: General type, output: Parsed/Validated values 
def _create_trigger(schedule_type: str, days: list[int] | None, time_str: str | None):
    """
    Create APScheduler trigger for single or multiple days.
    
    Args:
        days: Single day (as list with one item) or multiple days
              Example: [3] for Wednesday, [1,3,5] for Mon/Wed/Fri
    """
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
        if not days or not time_str:
            raise ValueError("Weekly requires day(s) and time")
        
        # Validate all days
        for d in days:
            if not (1 <= d <= 7):
                raise ValueError(f"Invalid day: {d}. Must be 1-7")
        
        hour, minute = map(int, time_str.split(":"))
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

def _get_next_run(trigger, schedule_type):
    """Ask APScheduler instead of guessing"""

    if schedule_type == "once":
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
            shell=False
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

    schedule_type = data.schedule_type.lower().strip()

    if schedule_type not in ("once","weekly"):
        raise ValueError("Invalid schedule type")

    trigger = _create_trigger(
        schedule_type,
        data.days_of_week,
        data.scheduled_time
    )

    next_run = _get_next_run(trigger, schedule_type)

    return Job(
        id=str(uuid.uuid4()),
        name=data.name.strip(),
        commands=data.commands,
        schedule_type=schedule_type,
        days_of_week=data.days_of_week,
        scheduled_time=data.scheduled_time,
        next_runtime=next_run,
        status= "active"
    )

def _schedule_single_job(job: Job) -> None:
    """Helper: Add one job to APScheduler"""

    if job.status != "active":
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
        kwargs={"commands": job.commands},
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
    

def _format_job_id(job_id: str | None) -> str:
    """Safely format job ID for display"""
    if job_id is None:
        return "NO_ID"
    return job_id[:8]

# --- PERSISTENCE (I/O operations) ---

def _init_db()-> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as conn:
        
        
        # === PERFORMANCE & SAFETY SETTINGS ===
        conn.execute("PRAGMA journal_mode=WAL;")       # Concurrent reads/writes
        conn.execute("PRAGMA synchronous=NORMAL;")     # Balance safety/speed
        conn.execute("PRAGMA cache_size=-10000;")      # 10MB cache
        conn.execute("PRAGMA temp_store=MEMORY;")      # Temp tables in RAM
        conn.execute("PRAGMA busy_timeout=5000;")      # Wait 5s on locks
        

        conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            name TEXT,
            commands TEXT,
            schedule_type TEXT,
            days_of_week TEXT,
            scheduled_time TEXT,
            next_run_time TEXT,
            status TEXT NOT NULL DEFAULT 'active'
        )
        """)

        # === INDEXES ===
        conn.execute("CREATE INDEX IF NOT EXISTS idx_next_run ON jobs(next_run_time)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON jobs(status)")

        logger.debug("Database Initialized")

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
# tenacity retry: Scheduler calling Database =  Machine calling machine:
# Persistence input/output: dataclass
def _insert_job(job: Job) -> Job:
    """Save job to database with retry"""

    with sqlite3.connect(DB_PATH) as conn:
        
        conn.execute("""
            INSERT INTO jobs (
                id, name, commands, schedule_type,
                days_of_week, scheduled_time,
                next_run_time, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job.id,
            job.name,
            json.dumps(job.commands), # dumps: stores to db
            job.schedule_type,
            json.dumps(job.days_of_week), # if you serialize → always deserialize symmetrically
            job.scheduled_time,
            job.next_runtime.isoformat(),
            job.status
        ))

        logger.info(f"Job saved: {job.name} (ID: {job.id})")
        return job

def _fetch_jobs() -> list[Job]:
    """Retrieve all jobs from database ordered by next run time
       Read from database fpr persistence
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT id, name, commands, schedule_type, 
            days_of_week, scheduled_time, next_run_time, status 
            FROM jobs 
            ORDER BY next_run_time
        """).fetchall()
    
    return [
        Job(
            id=r["id"],
            name=r["name"],
            commands=json.loads(r["commands"]),  # loads: retrieve from db
            schedule_type=r["schedule_type"],
            days_of_week=json.loads(r["days_of_week"]) if r["days_of_week"] else None,
            scheduled_time=r["scheduled_time"],
            next_runtime=datetime.fromisoformat(r["next_run_time"]),
            status=r["status"]
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
        if job.status == "active":
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
            logger.debug(f"  ⏸ [{display_id}] {job.name} (stopped)")

    return loaded


def _count_jobs() -> int:
    """Count total jobs in database"""

    # O(1), database optimized, constant time
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("SELECT COUNT(*) FROM jobs")
        return cursor.fetchone()[0]

def _validate_name(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return "My Job"
    return cleaned

# --- PERSISTENCE/OS LAYER (I/O) ---
def _install_windows_task() -> None:
    cmd = _build_windows_task_command()

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"Failed to create task: {result.stderr.strip()}")

def _install_systemd_user(content: str) -> Path:
    """Write service file to user's systemd directory"""
    path = Path.home() / ".config/systemd/user/scheduler.service"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path

def _install_systemd_system(content: str) -> Path:
    """Write service file to system systemd directory (requires sudo)"""
    path = Path("/etc/systemd/system/scheduler.service")
    
    try:
        result = subprocess.run(
            ["sudo", "tee", str(path)],
            input=content,
            text=True,
            capture_output=True
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr)
        return path
    except Exception:
        # Fallback: Show manual instructions
        typer.echo("\n✗ Automated install failed. Run manually:")
        typer.echo(f"  echo '{content}' | sudo tee {path}")
        typer.echo("  sudo systemctl daemon-reload")
        typer.echo("  sudo systemctl enable scheduler")
        typer.echo("  sudo systemctl start scheduler")
        raise typer.Exit(1)
      
# /////////////////////////////////////////////////
# //////////////////////////////////////////////////



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
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
        raise ValueError
    except (ValueError, TypeError):
        raise ValueError("Use HH:MM 24-hour (e.g., 16:00)")


def _validate_schedule_type(value: str) -> str:
    """Validate 'once' or 'weekly'"""
    value = value.lower().strip()
    if value in ("once", "weekly"):
        return value
    raise ValueError("Must be 'once' or 'weekly'")


def _validate_days(value: str) -> list[int]:
    """Parse comma-separated days, return list of ints 1-7"""
    try:
        days = [int(d.strip()) for d in value.split(",")]
        for d in days:
            if not (1 <= d <= 7):
                raise ValueError(f"Day {d} must be 1-7")
        return days
    except ValueError as e:
        if "must be 1-7" in str(e):
            raise
        raise ValueError("Use comma-separated numbers (e.g., 1,3,5)")

def _validate_commands(cmd: str)-> list[str]: 
    """Validate command has no dangerous patterns"""
    parts = shlex.split(cmd)  # split list[str] into str for generic prompt_until_valid() retry

    if not parts:
        raise ValueError("Command cannot be empty")

    forbidden = [";", "&", "|", "\n", "\r", "`", "$(", ">", "<"]

    for part in parts:
        for f in forbidden:
            if f in part:
                raise ValueError(f"Unsafe pattern: {f}")
    return parts
# ============================================
# ORCHESTRATION (public API)
# ============================================

def install_service(system: bool = False) -> tuple[str, list[str]]:
    """
    Install service for current platform.
    
    Args:
        system: If True, install system-wide (requires sudo on Linux)
    
    Returns:
        (success_message, next_steps_list)
    """
    platform = _detect_platform()
    
    if platform == "windows":
        _install_windows_task()
        return (
            "✓ Windows Task 'Scheduler' created",
            ["Task will run on system startup"]
        )
    
    elif platform == "linux":
        content = _build_systemd_service()
        
        if system:
            path = _install_systemd_system(content)
            return (
                f"✓ System service installed at {path}",
                [
                    "sudo systemctl daemon-reload",
                    "sudo systemctl enable scheduler",
                    "sudo systemctl start scheduler"
                ]
            )
        else:
            path = _install_systemd_user(content)
            return (
                f"✓ User service installed at {path}",
                [
                    "systemctl --user daemon-reload",
                    "systemctl --user enable scheduler",
                    "systemctl --user start scheduler"
                ]
            )
    
    elif platform == "mac":
        return (
            "✗ macOS not yet supported",
            ["Use launchd manually or run with --daemon flag"]
        )
    
    else:
        raise RuntimeError(f"Unsupported platform: {platform}")

    
# input/output: dataclass
def add_jobs(data: AddJobInput) -> Job:
    """Add a new scheduled job"""
    if _count_jobs() >= 100:
        raise ValueError("Maximum of 100 jobs reached")
    
    # Ensure job has ID before scheduling
    job = _build_job(data)
    if job.id is None:
        job.id = str(uuid.uuid4())

    
    _schedule_single_job(job)
    return _insert_job(job)

def list_jobs():
    """Retrieve all jobs"""

    return _fetch_jobs()


def remove_jobs(identifier: str) -> bool:
    """
    Remove job from scheduler and database.
    
    Args:
        identifier: Full ID, short ID prefix (min 4 chars), or exact name
    """

    # find the job
    job = _resolve_job_identifier(identifier)
    if not job:
        raise ValueError(f"Job '{identifier}' not found")
    
    job_id = job.id
    if job_id is None:
        raise ValueError(f"Job '{identifier}' not found")

    # Remove from scheduler memory
    try:
        scheduler.remove_job(job_id)
    except JobLookupError as e:
        logger.warning(f"Job {job_id} not in scheduler: {e}")  # Not in memory, continue

    # Remove from database
    removed = _remove_job_from_db(job_id)
    if removed:
        logger.info(f"Job '{job.name}' ({_format_job_id(job_id)}) removed")
    
    return removed

def resume_jobs(identifier: str) -> Job :
    """
    Resume a paused job.
    
    Args:
        identifier: Full ID, short ID prefix (min 4 chars), or exact name
    """
    # Find the job
    job = _resolve_job_identifier(identifier)
    if not job:
        raise ValueError(f"Job '{identifier}' not found")
    
    if job.status == "active":
        raise ValueError(f"Job '{job.name}' is already active")
    
    job_id = job.id
    if job_id is None:
        raise ValueError(f"Job '{job.name}' has no ID")

    # Resume in scheduler
    try:
        scheduler.resume_job(job_id)
    except Exception as e:
        raise RuntimeError(f"Failed to resume: {e}")
    
    # Update status in database
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE jobs SET status = 'active' WHERE id = ?", (job_id,))
    
    logger.info(f"Job '{job.name}' ({_format_job_id(job_id)}) resumed")
    return job
    


def start_scheduler_daemon():

    _load_jobs_from_database()

    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler daemon started")
    else:
        logger.info("Scheduler already running")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        scheduler.shutdown()
        logger.info("Scheduler stopped")
    

def stop_scheduler_daemon(wait: bool = True) -> bool:
    """Gracefully stop the scheduler"""
    if scheduler.running:
        logger.info("Stopping scheduler...")
        scheduler.shutdown(wait=wait)
        logger.info("Scheduler stopped")
        return True

    logger.info("Scheduler is not running")
    return False

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

T = TypeVar("T")

def _prompt_until_valid(
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
                logger.error(f"{error_prefix} Too many invalid attempts. Exiting.", err=True)
                raise typer.Exit(1)
        
        except KeyboardInterrupt:
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

def _validate_weekly_time(value: str) -> str:
    """Accept either 24-hour or 12-hour CLI time for weekly jobs."""
    try:
        return _validate_time_24h(value)
    except ValueError:
        return _validate_time_12h(value)

def _validate_once_datetime(value: str) -> str:
    """Validate a one-time CLI datetime and normalize it."""
    try:
        return datetime.fromisoformat(value.strip()).isoformat()
    except ValueError as e:
        raise ValueError("Use ISO datetime (e.g., 2026-04-19T13:00)") from e

def _collect_interactive_add_input() -> AddJobInput:
    """Collect add command input interactively."""
    name = _prompt_until_valid("Job name: ", _validate_name)
    commands = _prompt_until_valid(
        "Command: ",
        _validate_commands,
        max_attempts=3,
        error_prefix="Invalid command"
    )
    schedule_type = _prompt_until_valid(
        "Type (once/weekly): ",
        _validate_schedule_type,
        error_prefix="Must be 'once' or 'weekly'"
    )

    if schedule_type == "weekly":
        parsed_days = _prompt_until_valid(
            "Days (comma-separated, 1-7): ",
            _validate_days,
            error_prefix="Use numbers 1-7 separated by commas"
        )
        scheduled_time = _prompt_time_value()
        return AddJobInput(
            name=name,
            commands=commands,
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
        commands=commands,
        schedule_type=schedule_type,
        scheduled_time=f"{date_str}T{time_str}"
    )

def _collect_cli_add_input(
    name: str | None,
    command: str | None,
    schedule_type: str | None,
    days_list: str | None,
    scheduled_time: str | None
) -> AddJobInput:
    """Collect add command input from direct CLI options."""
    if name is None or command is None or schedule_type is None:
        raise ValueError("Missing required fields")

    normalized_type = _validate_schedule_type(schedule_type)
    commands = _validate_commands(command)

    if normalized_type == "weekly":
        if days_list is None or scheduled_time is None:
            raise ValueError("Weekly jobs require --days and --time")

        return AddJobInput(
            name=_validate_name(name),
            commands=commands,
            schedule_type=normalized_type,
            days_of_week=_validate_days(days_list),
            scheduled_time=_validate_weekly_time(scheduled_time)
        )

    if scheduled_time is None:
        raise ValueError("One-time jobs require --time")

    return AddJobInput(
        name=_validate_name(name),
        commands=commands,
        schedule_type=normalized_type,
        scheduled_time=_validate_once_datetime(scheduled_time)
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
            data = _collect_interactive_add_input()
        else:
            data = _collect_cli_add_input(
                name=name,
                command=command,
                schedule_type=schedule_type,
                days_list=days_list,
                scheduled_time=scheduled_time
            )
        
        # ✅ Step 2: Call orchestrator to create actual Job
        job = add_jobs(data)
        
        # ✅ Step 3: Display from Job object (has .id and .next_runtime)
        display_id = _format_job_id(job.id)
        local_time = job.next_runtime.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")
        
        typer.echo(f"\n✓ Job created: {display_id}")
        typer.echo(f"  Next run: {local_time}")
        
    except ValueError as e:
        typer.echo(f"✗ {e}", err=True)
        raise typer.Exit(1)

@app.command()
def list(verbose: bool = typer.Option(False, "--verbose", "-v")):
    """List all scheduled jobs"""

    jobs = list_jobs()
    
    if not jobs:
        typer.echo("No jobs scheduled")
        return
    
    for job in jobs:
        if verbose:
            typer.echo(f"\nID: {job.id}")
            typer.echo(f"  Name: {job.name}")
            typer.echo(f"  Command: {job.commands}")
            typer.echo(f"  Schedule: {job.schedule_type}")

            if job.days_of_week:
                days_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                days_str = ", ".join(days_names[d-1] for d in job.days_of_week)
                typer.echo(f"  Days: {days_str}")
            typer.echo(f"  Time: {job.scheduled_time}")
            typer.echo(f"  Next run: {job.next_runtime.astimezone(LOCAL_TZ)}")
            typer.echo(f"  Status: {job.status}")
        else:
             
            short_id = _format_job_id(job.id)
            local_time = job.next_runtime.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")
            typer.echo(f"[{short_id}] {job.name} → {local_time}")


@app.command()
def start():
    """Start the scheduler daemon"""
    
    # ===== CONSTITUTIONAL CHECK =====
    if os.name == 'nt':
        typer.echo("Starting scheduler (Windows mode)...")
    else:
        typer.echo("Starting scheduler (Ctrl+C to stop)...")
    start_scheduler_daemon()

    
@app.command()
def stop():
    """Stop the scheduler daemon"""
    try:
        stop = stop_scheduler_daemon()
        if stop:
            typer.echo("✓ Scheduler stopped")
        else:
            typer.echo("Scheduler already stopped")
    except Exception as e:
        typer.BadParameter(f"Error: {str(e)}")

def pause_job(identifier: str) -> Job:
    """
    Pause a scheduled job.
    
    Args:
        identifier: Full ID, short prefix, or exact name
    
    Returns:
        The paused Job object
    
    Raises:
        ValueError: Job not found or ambiguous
        RuntimeError: Failed to pause in scheduler
    """
    job = _resolve_job_identifier(identifier)
    
    if job.status == "paused":
        raise ValueError(f"Job '{job.name}' is already paused")
    
    job_id = job.id
    if job_id is None:
        raise ValueError(f"Job '{job.name}' has no ID")
    
    try:
        scheduler.pause_job(job_id)
    except Exception as e:
        raise RuntimeError(f"Failed to pause: {e}")
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE jobs SET status = 'paused' WHERE id = ?", (job_id,))
    
    logger.info(f"Job '{job.name}' ({_format_job_id(job_id)}) paused")
    return job

    

@app.command()
def pause(
    identifier: str = typer.Argument(..., help="Job ID, short prefix, or exact name")
):
    """Pause a scheduled job"""
    try:
        job = pause_job(identifier)
        typer.echo(f"⏸ Job '{job.name}' ({_format_job_id(job.id)}) paused")
        
    except ValueError as e:
        typer.echo(f"✗ {e}", err=True)
        raise typer.Exit(code=1)
    except RuntimeError as e:
        typer.echo(f"✗ {e}", err=True)
        raise typer.Exit(code=1)



@app.command()
def remove(
    identifier: str = typer.Argument(..., help="Job ID, short prefix, or exact name"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation")
):
    """Remove a scheduled job"""
    try:
        # Find job first to show what will be removed
        job = _resolve_job_identifier(identifier)
        if not job:
            typer.echo(f"✗ Job '{identifier}' not found", err=True)
            raise typer.Exit(1)
        
        display_id = _format_job_id(job.id)
        
        if not force and not typer.confirm(f"Remove '{job.name}' ({display_id})?"):
            typer.echo("Cancelled")
            raise typer.Exit(0)
        
        if remove_jobs(identifier):
            typer.echo(f"✓ Job '{job.name}' removed")
        else:
            typer.echo(f"✗ Failed to remove job", err=True)
            raise typer.Exit(1)
            
    except ValueError as e:
        typer.echo(f"✗ {e}", err=True)
        raise typer.Exit(1)


@app.command()
def resume(
    identifier: str = typer.Argument(..., help="Job ID, short prefix, or exact name")
):
    """Resume a paused job"""
    try:
        job = resume_jobs(identifier)
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
        
        msg, steps = install_service(system)
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
