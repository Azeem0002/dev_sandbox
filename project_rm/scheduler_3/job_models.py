"""Shared job/domain models for scheduler.

Persistence and orchestration both rely on the same meanings for job status,
schedule type, and schedule-time conversion.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

try:
    from .runtime_support import get_local_timezone
except ImportError:
    from runtime_support import get_local_timezone

# Shared timezone anchor for schedule parsing/formatting.
# The scheduler and database adapter both depend on this meaning.
LOCAL_TZ = get_local_timezone()


# Object: An instance of a class, Noun: Name of thing
class ScheduleType(StrEnum):
    """Allowed schedule shapes understood by the scheduler domain."""
    ONCE = "once"
    WEEKLY = "weekly"


class JobStatus(StrEnum):
    """Persisted/lived state of a scheduled job."""
    ACTIVE = "active"
    PAUSED = "paused"


@dataclass
class Job:
    """Stored job entity shared across orchestration and persistence."""

    id: str | None          # Database primary key (None until saved)
    name: str               # Human-readable label ("Daily Backup")
    command: list[str]      # Shell command to execute
    schedule_type: ScheduleType
    days_of_week: list[int] | None  # 1=Monday..7=Sunday (only for weekly)
    scheduled_time: datetime | None # "21:00" or "2026-04-14T15:30:00"
    next_runtime: datetime          # Pre-calculated UTC timestamp (core driver!)
    status: JobStatus = JobStatus.ACTIVE


def normalize_job_name(value: str) -> str:
    """Normalize and validate the user-facing job name without changing its display casing."""
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Name cannot be empty")

    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        # Only strip matching quote wrappers. Without the quote check, a valid name
        # like "aba" would lose its first/last character just because they match.
        inner = cleaned[1:-1].strip()
        if not inner:
            raise ValueError("Name cannot be empty")
        cleaned = inner

    if not any(char.isalnum() for char in cleaned):
        raise ValueError("Name must include at least one letter or number")
    return cleaned


def normalize_job_name_for_lookup(value: str) -> str:
    """Build a case-insensitive comparison key for job-name lookup/cleanup."""
    return normalize_job_name(value).casefold()


# Storage/domain parser
def parse_scheduled_time_from_storage(
    schedule_type: ScheduleType,
    value: str | datetime | None,
) -> datetime | None:
    """Normalize persisted/input schedule values into Job's datetime field.
    A universal translator that converts different time input formats into one standard format.
    """
    if value is None:
        return None  # Nothing to convert

    if isinstance(value, datetime):
        parsed = value  # Already datetime, no parsing needed
    elif schedule_type == ScheduleType.ONCE:
        parsed = datetime.fromisoformat(value)  # Converts ISO string -> datetime
    else:
        try:
            hour, minute = map(int, value.split(":"))  # "09:00" -> hour=9, minute=0
            # map(): apply int to each item from value.split(":")

            # Weekly jobs only need a stable local time-of-day anchor.
            # We pick a fake date because weekly recurrence cares about time, not date.
            parsed = datetime(2000, 1, 3, hour, minute, tzinfo=LOCAL_TZ)

        except ValueError:
            # Backward compatibility for older rows stored as full ISO datetimes (date+time).
            parsed = datetime.fromisoformat(value)
    
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=LOCAL_TZ)
    return parsed.astimezone(LOCAL_TZ)

# Persistence layer formatter
def serialize_scheduled_time_for_storage(
    value: datetime | None,
    schedule_type: ScheduleType,
) -> str | None:
    """
    STORAGE FORMATTER: datetime -> string for DB / JSON
    """
    if value is None:
        return None
    if schedule_type == ScheduleType.WEEKLY:  # Weekly: Store only time (date is irrelevant)
        # Weekly jobs are stored as a stable local clock time.
        return value.astimezone(LOCAL_TZ).strftime("%H:%M")  # "14:30"
    return value.isoformat()  # Machine storage format: "2026-04-26T14:30:00+01:00"


def format_job_id(job_id: str | None) -> str:
    """Safely format job ID for display."""
    if job_id is None:
        return "NO_ID"
    return job_id[:8]
