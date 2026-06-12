#!/usr/bin/env python3
"""SQLite database adapter for lead_finder_7."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

try:
    from .models import LeadIntent, LeadRun, LeadSource, LeadTarget
    from .runtime_support import get_platform_dirs
except ImportError:
    from models import LeadIntent, LeadRun, LeadSource, LeadTarget
    from runtime_support import get_platform_dirs


# ============================================
# Database adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================
dirs = get_platform_dirs()


def _get_db_path() -> Path:
    """Return the database file path."""
    # One DB file can hold many lead runs; rows provide separation by product/region.
    return Path(dirs.user_data_dir) / "lead_finder.db"


DB_PATH = _get_db_path()


def _init_db() -> None:
    """Initialize database schema and indexes."""
    # Init is the explicit setup step, so parent-dir creation belongs here.
    DB_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS lead_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product TEXT NOT NULL,
            region TEXT NOT NULL,
            intent TEXT NOT NULL,
            leads_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_lead_runs_created_at ON lead_runs(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_lead_runs_product_region ON lead_runs(product, region)")
        logger.debug("Lead finder database initialized")


def _lead_to_dict(item: LeadTarget) -> dict:
    """Convert a lead target dataclass into a JSON-safe dict."""
    data = asdict(item)
    data["intent"] = item.intent.value
    data["source"] = item.source.value
    data["discovered_at"] = item.discovered_at.isoformat()
    return data


def _row_to_lead_run(row: sqlite3.Row) -> LeadRun:
    """Rehydrate one SQLite row back into an app-level result model."""
    leads = [
        LeadTarget(
            product=item["product"],
            region=item["region"],
            intent=LeadIntent(item["intent"]),
            source=LeadSource(item["source"]),
            title=item["title"],
            url=item["url"],
            score=float(item["score"]),
            note=item["note"],
            discovered_at=datetime.fromisoformat(item["discovered_at"]),
        )
        for item in json.loads(row["leads_json"])
    ]
    return LeadRun(
        product=row["product"],
        region=row["region"],
        intent=LeadIntent(row["intent"]),
        leads=leads,
        created_at=datetime.fromisoformat(row["created_at"]),
    )


@retry(
    retry=retry_if_exception_type(sqlite3.OperationalError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    reraise=True,
)
def _insert_lead_run(run: LeadRun) -> LeadRun:
    """Save one lead search run to SQLite."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO lead_runs (product, region, intent, leads_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run.product, run.region, run.intent.value, json.dumps([_lead_to_dict(item) for item in run.leads]), run.created_at.isoformat()),
        )
    return run


def _fetch_recent_runs(limit: int = 20) -> list[LeadRun]:
    """Load recent lead runs from SQLite."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM lead_runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [_row_to_lead_run(row) for row in rows]


# ============================================
# Public adapter API - stable reusable surface
# ============================================
def get_db_path() -> Path:
    """Return the database file path."""
    return DB_PATH


def init_db() -> None:
    """Public wrapper for initializing lead finder persistence."""
    _init_db()


def insert_lead_run(run: LeadRun) -> LeadRun:
    """Public wrapper for saving one lead search run."""
    return _insert_lead_run(run)


def fetch_recent_runs(limit: int = 20) -> list[LeadRun]:
    """Public wrapper for loading recent lead runs."""
    return _fetch_recent_runs(limit)
