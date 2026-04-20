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
from typing import Literal


APP_NAME = "scheduler"
APP_AUTHOR= "Al"

class AddJobInput:
    name: str
    command: list[str]
    schedule_type: str
    days_of_week: list[int] | None = None
    schedule_time: str | None = None
    status: Literal["active", "paused"]

class Job:
    id: str
    name: str
    command: list[str]
    schedule_type: str
    days_of_week: list[int] | None= None
    schedule_time: str | None = None
    next_run_time: datetime
    status: Literal["active", "paused"]


def _count_jobs():
    with sqlite3.connect(DB_PATH) as 

def add_jobs(data: AddJobInput)-> Job:

    if _count_job > 100:
        raise ValueError("Maximum of 100 jobs reached")