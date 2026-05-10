#!/usr/bin/env python3
"""
Database adapter for scheduler - handles all SQLite persistence operations.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import cast

from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

try:
    from .job_models import (  # Relative import (package)
        Job,
        JobStatus,
        ScheduleType,
        parse_scheduled_time_from_storage,
        format_job_id,
        serialize_scheduled_time_for_storage,
    )
    from .runtime_support import get_platform_dirs
except ImportError:
    from job_models import (  # Absolute import (script)
        Job,
        JobStatus,
        ScheduleType,
        parse_scheduled_time_from_storage,
        format_job_id,
        serialize_scheduled_time_for_storage,
    )
    from runtime_support import get_platform_dirs


# ============================================
# Database adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================
# Platform-appropriate data directory
dirs = get_platform_dirs()
# if path is a file, create a .parent, else it pathlib will make path a directory

def _get_db_path() -> Path:
    """Return the database file path."""
    return Path(dirs.user_data_dir) / "jobs.db"


def _normalize_job_name_for_storage(value: str) -> str:
    """Normalize job name for storage."""
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Name cannot be empty")

    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        inner = cleaned[1:-1].strip()
        if not inner:
            raise ValueError("Name cannot be empty")
        cleaned = inner

    if not any(char.isalnum() for char in cleaned):
        raise ValueError("Name must include at least one letter or number")
    return cleaned.casefold()


def _delete_jobs_by_ids(conn: sqlite3.Connection, job_ids: list[str]) -> int:
    """Delete multiple jobs by their IDs."""
    if not job_ids:
        return 0
    conn.executemany("DELETE FROM jobs WHERE id = ?", [(job_id,) for job_id in job_ids])
    # delete rows where id matches. Runs the same SQL multiple times with different values.
    return len(job_ids)


def _cleanup_jobs_table(conn: sqlite3.Connection) -> int:
    """Remove invalid or duplicate jobs from the database."""
    conn.row_factory = sqlite3.Row #  Make rows accessible by column name (like dictionaries access) e.g row["id"]
    rows = conn.execute("""
        SELECT id, name, next_run_time_utc
        FROM jobs
        ORDER BY next_run_time_utc, id
    """).fetchall() # rows = conn.e..: Returns list of all matching rows
    # ORDER BY ...).fetchall(): Get all jobs ordered by next run time, then by ID
    
    invalid_ids: list[str] = []
    duplicate_ids: list[str] = [] # List: order matters, just collecting
    seen_names: set[str] = set()  # Set: fast "is this already here?" check
    # Three buckets: invalid ids, duplicate ids, and names already seen.

    for row in rows:  # Check each job
        job_id = cast(str | None, row["id"]) # Get ID safely
        # cast: Tells type checker; "Trust me, this is str|None" because row["id"] returns Any. ignored at runtime
        raw_name = cast(str, row["name"]) # Get name safely
        # Extract ID and name from each row. cast() tells type checker what to expect.

        try: # Try to normalize name. If fails (empty/invalid), mark for removal.
            normalized_name = _normalize_job_name_for_storage(raw_name)
            # .casefold(): More aggressive .lower(), designed for case-insensitive comparison:
            # Best fix: Use casefold() for name comparisons (it handles international characters better).
        
        except ValueError:
            if job_id:
                invalid_ids.append(job_id)  # Collect bad id for deletion
            continue  # Skip to next row

        # If name already seen, it's a duplicate. Otherwise, add to seen set.
        if normalized_name in seen_names:  # if duplicate name is detected
            if job_id:
                duplicate_ids.append(job_id) # add to list of duplicates for deletion
            continue  # skip processing

        seen_names.add(normalized_name)  # First time seeing this name

    removed_count = _delete_jobs_by_ids(conn, invalid_ids + duplicate_ids)
    # Delete all bad jobs marked as invalid or duplicate.

    # Log what was removed and why.
    for job_id in invalid_ids: 
        logger.warning(f"Removed invalid job with empty name ({format_job_id(job_id)})")
    for job_id in duplicate_ids:
        logger.warning(f"Removed duplicate job name ({format_job_id(job_id)})")

    return removed_count # Report total number of jobs removed.


DB_PATH = _get_db_path() # resolved module-level path

def _init_db() -> None:
    """Initialize database schema(blueprint/structure) and indexes."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # create database folder if it doesn't exist

    with sqlite3.connect(DB_PATH) as conn: # Create tables and indexes
    # with: opens DB connection, auto commits on success, auto rollback on error, auto closes connection
    # sqlite3.connect: The database connection object.Run SQL command
        
        # === PERFORMANCE & SAFETY SETTINGS ===
        conn.execute("PRAGMA journal_mode=WAL;")  # Allows concurrent reads/writes simultaneously so that they don't block each other
        conn.execute("PRAGMA synchronous=NORMAL;")  # Balance safety and speed. Save document every 5 seconds vs every keystroke
        conn.execute("PRAGMA cache_size=-10000;")  # 10MB cache
        conn.execute("PRAGMA temp_store=MEMORY;")  # Temp tables in RAM -> faster
        conn.execute("PRAGMA busy_timeout=5000;")  # Wait 5 seconds if DB is locked instead of failing immediately
        # PRAGMA: Tunning engine setting: improves performance. SQLITE specific

        # conn.execute: Run this sqlite command
        conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, 
            name TEXT UNIQUE,
            command TEXT,
            schedule_type TEXT,
            days_of_week TEXT,
            scheduled_time_local TEXT,
            next_run_time_utc TEXT,
            status TEXT NOT NULL DEFAULT 'active'
        )
        """)
        # PRIMARY KEY = Unique identifier for each row. No two jobs can have the same ID.
        # TEXT NOT NULL DEFAULT 'active' = required. stores TEXT, Can't be NULL, If not specified, defaults to fallback value 'active'
        # jobs is a table name
        # schedule_time: when user want's to run in local time
        # next_run_time: actual execution time in UTC

        
        removed_count = _cleanup_jobs_table(conn)
        if removed_count:
            logger.warning(f"Removed {removed_count} invalid/duplicate job(s) during startup cleanup")

        # === INDEXES ===
        conn.execute("CREATE INDEX IF NOT EXISTS idx_next_run ON jobs(next_run_time_utc)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON jobs(status)")
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_unique_name
            ON jobs(lower(trim(name)))
            WHERE trim(name) <> ''
        """)
        # ON jobs(lower(trim(name))): remove white spaces and convert to lower case
        # WHERE trim(name) <> '' : meaning: enforce uniqueness ignoring case, space. skip empty names. Only index non-empty names

        logger.debug("Database Initialized")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
def _insert_job(job: Job) -> Job:
    """Save job to database with retry."""
    with sqlite3.connect(DB_PATH) as conn:
        try:
            conn.execute("""
                INSERT INTO jobs (
                    id, name, command, schedule_type,
                    days_of_week, scheduled_time_local,
                    next_run_time_utc, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job.id,  # Plane → string
                job.name, # Plane → string
                json.dumps(job.command), # json.dumps converts list[str] to json string for database storage
                job.schedule_type.value,  # Enum → string ("once"). Python's Enum automatically provides .value
                json.dumps(job.days_of_week),
                serialize_scheduled_time_for_storage(job.scheduled_time, job.schedule_type),  # datetime → string
                job.next_runtime.isoformat(), # datetime → ISO string
                job.status.value # Enum → string ("active")
                #.value → "active": (built-in Enum attribute)

            ))
        # dumps = "Dump String" (serialize). loads = "Load String" (deserialize).
        except sqlite3.IntegrityError as e:
            raise ValueError(f"Job name '{job.name}' already exists") from e

        logger.info(f"Job saved: {job.name} (ID: {job.id})")
        return job


def _fetch_jobs() -> list[Job]:
    """Retrieve all jobs from database ordered by next run time."""

    # Python communicates with SQLite (written in C)
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        # row_factory: Access by column name: "abc123"
        rows = conn.execute("""
            SELECT id, name, command, schedule_type,
            days_of_week, scheduled_time_local, next_run_time_utc, status
            FROM jobs
            ORDER BY next_run_time_utc
        """).fetchall() # .fetchall()= a method on the cursor object, which is part of sqlite3.
        # execute() → runs parameterized query command
        # .fetchall() → retrieves results: Give me all rows from the query result”

    return [ 
        Job( 
            id=r["id"], # Plane → string
            name=r["name"],  # Plane → string
            command=json.loads(r["command"]),  # JSON string → Python list. json.loads returns any
            schedule_type=ScheduleType(r["schedule_type"]), # String → Enum
            days_of_week=json.loads(r["days_of_week"]) if r["days_of_week"] else None,  # JSON string → Python list
            scheduled_time=parse_scheduled_time_from_storage(
                ScheduleType(r["schedule_type"]),
                r["scheduled_time_local"]
            ),  # String → datetime
            next_runtime=datetime.fromisoformat(r["next_run_time_utc"]), # ISO string → datetime
            status=JobStatus(r["status"])  # String → Enum
        )
        for r in rows  # ← This is a list comprehension. [expression for item in iterable]
    ] 


def _remove_job_from_db(job_id: str) -> bool:
    """Remove single job from database."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,)) # Speak command (cursor). What flows through the connection. 
        # ? = Placeholder for parameterized query (prevents SQL injection).
        return cursor.rowcount > 0


def _count_jobs() -> int:
    """Count total jobs in database."""
    with sqlite3.connect(DB_PATH) as conn: # Open connection to database
        cursor = conn.execute("SELECT COUNT(*) FROM jobs") # query(parameterized query): SELECT COUNT(*) FROM jobs: count everything
        # ask DB: “how many rows?”

        return cursor.fetchone()[0]
    # .fetchone() returns the first row (as a tuple) e.g (8, 0). [0] extracts the first value: int:8.


def _count_jobs_by_status() -> dict[str, int]:  # Returns a dictionary: {"active": 5, "paused": 3}.
    """Count jobs grouped by status."""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("""
            SELECT status, COUNT(*) AS total
            FROM jobs
            GROUP BY status
        """).fetchall() # SQL: "For each status, count how many jobs." Result: [("active", 5), ("paused", 3)].

    # Start with zeros for both statuses (prevents missing keys).
    counts = {JobStatus.ACTIVE.value: 0, JobStatus.PAUSED.value: 0}
    for status, total in rows: # For each row: extract status name and total count. Store in dictionary.
        counts[str(status)] = int(total)
    return counts # Returns {"active": 5, "paused": 3}.


def _update_job_status(job_id: str, status: JobStatus) -> None:
    """Update job status in database."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status.value, job_id))
        # In the jobs table, find the row with this ID, and change its status to this value.
        # ?: Prevents SQL injection. Never do: f"WHERE id = {job_id}"

# ============================================
# Public adapter API - stable reusable surface
# ============================================

def get_db_path() -> Path:
    """Return the database file path."""
    return _get_db_path()

def init_db() -> None:
    """Public wrapper for initializing the scheduler database schema."""
    _init_db()


def insert_job(job: Job) -> Job:
    """Public wrapper for inserting one scheduler job into SQLite."""
    return _insert_job(job)


def fetch_jobs() -> list[Job]:
    """Public wrapper for loading scheduler jobs from SQLite."""
    return _fetch_jobs()


def remove_job_from_db(job_id: str) -> bool:
    """Public wrapper for deleting one scheduler job row by ID."""
    return _remove_job_from_db(job_id)


def count_jobs() -> int:
    """Public wrapper for counting total scheduler jobs."""
    return _count_jobs()


def count_jobs_by_status() -> dict[str, int]:
    """Public wrapper for counting scheduler jobs grouped by status."""
    return _count_jobs_by_status()


def update_job_status(job_id: str, status: JobStatus) -> None:
    """Public wrapper for updating one scheduler job status."""
    _update_job_status(job_id, status)
