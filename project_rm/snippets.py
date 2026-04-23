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
from typing import Literal, Any

from enum import StrEnum
class ScheduleType(StrEnum):
    ONCE = "once"
    WEEKLY = "weekly"

class JobStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"

def _require_non_empty_text(value: str, field_name: str)-> str:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned:
        raise ValueError(f"{field_name} cannot be empty")
    return cleaned

def _validate_name(value: str)-> str:

    return _require_non_empty_text(value, "name")

def _validate_command_parts(value: list[str])-> list[str]:
    if not value:
        raise ValueError("Command cannot be empty")
    cleaned = [part.strip() for part in value if part.strip()]

    forbidden = [";", "|", "`"]
    for part in value:
        for token in forbidden:
            if token in part:
                raise ValueError(f"Unsafe pattern: {token}")
    return cleaned





from pydantic import BaseModel, ConfigDict, field_validator, model_validator
class AppConfig(BaseModel):
    model_config= ConfigDict(frozen=True)

    app_name: str= "scheduler"
    app_author: str= "Az"
    storage_timezone: str = "UTC"
    local_timezone: str = "Africa/Lagos"

class AddJobInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name:str
    command: str
    schedule_type: ScheduleType
    days_of_week: list[int] | None = None
    schedule_time: str | None = None

    @field_validator("name")
    @classmethod
    def _adapt_name(cls, value: str):
        return _validate_name(value)
    
    @field_validator("command")
    @classmethod
    def adapt_command(cls, value: list[str])-> list[str]:
        return _validate_command_parts(value)
    
    @field_validator("schedule_type", mode="before")
    @classmethod
    def _adapt_schedule_type(cls, value: Any)-> ScheduleType:
        if not isinstance(value, str):
            raise ValueError("Value must be a text")
        return _validated_schedule_type(value)
    
    @field_validator("days_of_week")
    @classmethod
    def _adapt_days_of_week(cls, value: list[int] | None)-> list[int] | None:
        return _validate_days_of_week(value)
    
    @field_validator("days_of_week")
    @classmethod
    def adapt_schedule_time(cls, value: str | None)-> str | None:
        return _validate_schedule_time(value)
    
    @model_validator(mode="after")
    def _validate_schedule_shape(self)-> "AddJobInput":
        if self.schedule_type is ScheduleType.ONCE:
            if not self.schedule_time:
                raise ValueError("One time job require a schedule time")
            if self.days_of_week is not None:
                raise ValueError("One time Job does not accept days of week")
            
        if not self.schedule_time:
            raise ValueError("Weekly jobs require a Schedule Time")
        if not self.days_of_week:
            raise ValueError("Weekly jobs require at least a day")
        return self

@dataclass
class Job:
    id: str | None
    name: str
    command: list[str]
    schedule_type: ScheduleType
    days_of_week: list[int]
    scheduled_time: datetime | None
    next_runtime: datetime
    status: JobStatus= JobStatus.ACTIVE

def _coerce_job_schedule_time(
        schedule_type: ScheduleType,
        value: str
)-> datetime | None:
    if value is None:
        return None
    
    if isinstance(value, datetime):
        parsed= value
    elif schedule_type is ScheduleType.ONCE:
        parsed = datetime.fromisoformat(value)
    else:
        hour, minute = map(int, value.split(":"))
        parsed = datetime(2000, 1, 3, hour, minute, tzinfo=LOCAL_TZ)
    
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=LOCAL_TZ)
    return parsed.astimezone(LOCAL_TZ)

def _serialize_scheduled_time(value: datetime | None)-> str | None:
    if value is None:
        return None
    return value.isoformat()

def _format_scheduled_time(job: Job)-> str:
    if job.scheduled_time is None:
        return "-"
    if job.scheduled_time is ScheduleType.WEEKLY:
        return job.scheduled_time.astimezone(LOCAL_TZ).strftime("%H:%M")
    return job.scheduled_time.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%m")







def _validate_schedule_time(value: str | None)-> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None

def _validate_days_of_week(value: list[int] | None)-> list[int] | None:
    if value is None:
        return None
    cleaned = sorted(set(value))
    for day in cleaned:
        if not (1<= day <=7):
            raise ValueError(f"{day}: days must be 1-7")
    return cleaned

def _validated_schedule_type(value: str)-> ScheduleType:
    if value == ScheduleType.ONCE.value:
        return ScheduleType.ONCE
    elif value== ScheduleType.WEEKLY.value:
        return ScheduleType.WEEKLY
    else:
        raise ValueError("value must be once or weekly")

        









from zoneinfo import ZoneInfo
APP_CONFIG= AppConfig()
STORAGE_TZ= ZoneInfo(APP_CONFIG.storage_timezone)
LOCAL_TZ= ZoneInfo(APP_CONFIG.local_timezone)

dirs = PlatformDirs(APP_CONFIG.app_name, APP_CONFIG.app_author)
DB_PATH= Path(dirs.user_data_dir)

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.base import JobLookupError

scheduler = BackgroundScheduler(APP_CONFIG.local_timezone)

def _setup_env():

    LOG_DIR = Path(dirs.user_log_dir)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.debug("Failed to create directory")
        raise PermissionError(f"Failed to create directory") from e
    
    file_log = LOG_DIR / "scheduler.log"
    return file_log

import os
import sys
def _setup_logger(file_log: Path)-> None:

    ENV= os.getenv("APP_ENV", "dev")
    logger.remove()

    if ENV == "prod":
        logger.add(
            sink= sys.stdout,
            level= "INFO",
            enqueue=True
        )
    else:
        logger.add(
            sink= sys.stdout,
            level= "DEBUG",
            format= "<cyan>{time:YYYY-MM-DD HH:mm:ss}</cyan> | <level>{level: <8}</level> | {module}.{function}:{line} | <level>{message}</level>",
            colorize=True,
            enqueue= True,
        )

    logger.add(
        sink= file_log,
        level= "DEBUG",
        format= "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {module}.{function}:{line} | {message}",
        rotation= "1 MB",
        retention="3 days",
        compression="zip",
        enqueue=True,
    )




    

    


        
        

    

    
    

app = typer.Typer()

@app.callback()
def init():
    file_log= _setup_env()
    _setup_logger(file_log)

if __name__=="__main__":
    app()