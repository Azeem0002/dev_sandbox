from __future__ import annotations
"""Core models for adbot_9."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import uuid4


class AdPlatform(StrEnum):
    """Ad platforms the MVP can prepare campaign copy for."""

    META = "meta"
    GOOGLE = "google"
    TIKTOK = "tiktok"
    WHATSAPP = "whatsapp"


class CampaignGoal(StrEnum):
    """Business goal the ad campaign should optimize toward."""

    AWARENESS = "awareness"
    LEADS = "leads"
    SALES = "sales"
    RETARGETING = "retargeting"


class DemandSource(StrEnum):
    """Free demand-signal source categories used by the MVP."""

    SEARCH = "search"
    SOCIAL = "social"
    MARKETPLACE = "marketplace"


@dataclass(frozen=True)
class CampaignRequest:
    """Clean input for building a targeted ad campaign plan."""

    product: str
    region: str
    cities: tuple[str, ...]
    platform: AdPlatform
    goal: CampaignGoal
    audience: str
    daily_budget: float
    max_locations: int


@dataclass
class CityDemandSignal:
    """One region/city demand signal used for ad targeting."""

    product: str
    region: str
    city: str | None
    source: DemandSource
    query: str
    search_url: str
    score: float
    note: str
    discovered_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AdCreative:
    """One platform-ready ad draft for a recommended location."""

    platform: AdPlatform
    city: str | None
    headline: str
    primary_text: str
    call_to_action: str
    landing_page_hint: str


@dataclass
class CampaignPlan:
    """Full campaign recommendation returned by orchestration."""

    product: str
    region: str
    platform: AdPlatform
    goal: CampaignGoal
    audience: str
    daily_budget: float
    demand_signals: list[CityDemandSignal] = field(default_factory=list)
    creatives: list[AdCreative] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid4().hex)
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(frozen=True)
class ExportedCampaign:
    """Export text plus metadata for a saved campaign plan."""

    plan_id: str
    content: str
    created_at: datetime = field(default_factory=datetime.utcnow)
