from __future__ import annotations
"""Core models for lead_finder_7."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class LeadIntent(StrEnum):
    """Whether the user is looking for buyers, sellers, or both."""
    BUYERS = "buyers"
    SELLERS = "sellers"
    BOTH = "both"


class LeadSource(StrEnum):
    """Free lead-source categories supported by the MVP."""
    SEARCH = "search"
    MARKETPLACE = "marketplace"
    SOCIAL = "social"


@dataclass(frozen=True)
class LeadSearchRequest:
    """Clean input for finding buyer/seller lead targets."""
    product: str
    region: str
    city: str | None
    intent: LeadIntent
    max_results: int


@dataclass
class LeadTarget:
    """One buyer/seller lead target a human can inspect."""
    product: str
    region: str
    city: str | None
    intent: LeadIntent
    source: LeadSource
    title: str
    url: str
    score: float
    note: str
    discovered_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class LeadRun:
    """Full app-level result returned by orchestration."""
    product: str
    region: str
    city: str | None
    intent: LeadIntent
    leads: list[LeadTarget] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
