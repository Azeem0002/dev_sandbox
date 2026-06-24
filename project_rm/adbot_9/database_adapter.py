#!/usr/bin/env python3
"""SQLite database adapter for adbot_9."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

try:
    from .models import AdCreative, AdPlatform, CampaignGoal, CampaignPlan, CityDemandSignal, DemandSource
    from .runtime_adapter import get_platform_dirs
except ImportError:
    from models import AdCreative, AdPlatform, CampaignGoal, CampaignPlan, CityDemandSignal, DemandSource
    from runtime_adapter import get_platform_dirs


# ============================================
# Database adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================
dirs = get_platform_dirs()


def _get_db_path() -> Path:
    """Return the database file path."""
    # Keep path getters pure: return the path only.
    return Path(dirs.user_data_dir) / "adbot.db"


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
        CREATE TABLE IF NOT EXISTS campaign_plans (
            id TEXT PRIMARY KEY,
            product TEXT NOT NULL,
            region TEXT NOT NULL,
            platform TEXT NOT NULL,
            goal TEXT NOT NULL,
            audience TEXT NOT NULL,
            daily_budget REAL NOT NULL,
            demand_signals_json TEXT NOT NULL,
            creatives_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_campaign_plans_created_at ON campaign_plans(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_campaign_plans_product_region ON campaign_plans(product, region)")
        logger.debug("AdBot database initialized")


def _signal_to_dict(item: CityDemandSignal) -> dict:
    """Convert a demand signal dataclass into a JSON-safe dict."""
    data = asdict(item)
    data["source"] = item.source.value
    data["discovered_at"] = item.discovered_at.isoformat()
    return data


def _creative_to_dict(item: AdCreative) -> dict:
    """Convert an ad creative dataclass into a JSON-safe dict."""
    data = asdict(item)
    data["platform"] = item.platform.value
    return data


def _row_to_campaign_plan(row: sqlite3.Row) -> CampaignPlan:
    """Rehydrate one SQLite row back into an app-level campaign plan."""
    signals = [
        CityDemandSignal(
            product=item["product"],
            region=item["region"],
            city=item.get("city"),
            source=DemandSource(item["source"]),
            query=item["query"],
            search_url=item["search_url"],
            score=float(item["score"]),
            note=item["note"],
            discovered_at=datetime.fromisoformat(item["discovered_at"]),
        )
        for item in json.loads(row["demand_signals_json"])
    ]
    creatives = [
        AdCreative(
            platform=AdPlatform(item["platform"]),
            city=item.get("city"),
            headline=item["headline"],
            primary_text=item["primary_text"],
            call_to_action=item["call_to_action"],
            landing_page_hint=item["landing_page_hint"],
        )
        for item in json.loads(row["creatives_json"])
    ]
    return CampaignPlan(
        id=row["id"],
        product=row["product"],
        region=row["region"],
        platform=AdPlatform(row["platform"]),
        goal=CampaignGoal(row["goal"]),
        audience=row["audience"],
        daily_budget=float(row["daily_budget"]),
        demand_signals=signals,
        creatives=creatives,
        created_at=datetime.fromisoformat(row["created_at"]),
    )


@retry(
    retry=retry_if_exception_type(sqlite3.OperationalError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    reraise=True,
)
def _insert_campaign_plan(plan: CampaignPlan) -> CampaignPlan:
    """Save one campaign plan to SQLite."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO campaign_plans (
                id, product, region, platform, goal, audience, daily_budget,
                demand_signals_json, creatives_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan.id,
                plan.product,
                plan.region,
                plan.platform.value,
                plan.goal.value,
                plan.audience,
                plan.daily_budget,
                json.dumps([_signal_to_dict(item) for item in plan.demand_signals]),
                json.dumps([_creative_to_dict(item) for item in plan.creatives]),
                plan.created_at.isoformat(),
            ),
        )
    return plan


def _fetch_campaign_plan(plan_id: str) -> CampaignPlan | None:
    """Fetch one campaign plan by id."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM campaign_plans WHERE id = ?", (plan_id,)).fetchone()
    return _row_to_campaign_plan(row) if row else None


def _fetch_recent_campaign_plans(limit: int = 20) -> list[CampaignPlan]:
    """Load recent campaign plans from SQLite."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM campaign_plans ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [_row_to_campaign_plan(row) for row in rows]


# ============================================
# Public adapter API - stable reusable surface
# ============================================
def get_db_path() -> Path:
    """Return the database file path."""
    return DB_PATH


def init_db() -> None:
    """Public wrapper for initializing AdBot persistence."""
    _init_db()


def insert_campaign_plan(plan: CampaignPlan) -> CampaignPlan:
    """Public wrapper for saving one campaign plan."""
    return _insert_campaign_plan(plan)


def fetch_campaign_plan(plan_id: str) -> CampaignPlan | None:
    """Public wrapper for fetching a campaign plan by id."""
    return _fetch_campaign_plan(plan_id)


def fetch_recent_campaign_plans(limit: int = 20) -> list[CampaignPlan]:
    """Public wrapper for loading recent campaign plans."""
    return _fetch_recent_campaign_plans(limit)
