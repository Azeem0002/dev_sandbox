"""Demand-source adapter for adbot_9.

Free MVP stance: build transparent demand-signal searches and score them
locally. A real provider like Google Ads Keyword Planner, DataForSEO, or a
marketplace API can replace this adapter later without changing orchestration.
"""

from __future__ import annotations

import urllib.parse
from datetime import datetime

try:
    from .models import CampaignGoal, CampaignRequest, CityDemandSignal, DemandSource
except ImportError:
    from models import CampaignGoal, CampaignRequest, CityDemandSignal, DemandSource


# ============================================
# Demand adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================
def _build_public_search_url(query: str) -> str:
    """Build a public search URL a human can inspect."""
    return f"https://www.google.com/search?{urllib.parse.urlencode({'q': query})}"


def _location_label(region: str, city: str | None) -> str:
    """Return human-readable targeting location from optional city plus region."""
    return f"{city} {region}" if city else region


def _goal_query_words(goal: CampaignGoal) -> tuple[str, ...]:
    """Return search words that match the user's campaign goal."""
    if goal == CampaignGoal.LEADS:
        return ("near me", "quote", "contact", "supplier")
    if goal == CampaignGoal.SALES:
        return ("buy", "price", "discount", "delivery")
    if goal == CampaignGoal.RETARGETING:
        return ("reviews", "compare", "best", "alternative")
    return ("best", "popular", "trending", "recommended")


def _city_queries(request: CampaignRequest, city: str | None) -> tuple[tuple[DemandSource, str], ...]:
    """Build transparent local demand queries for one target location."""
    product = request.product
    location = _location_label(request.region, city)
    goal_words = " ".join(_goal_query_words(request.goal))
    return (
        (DemandSource.SEARCH, f"{goal_words} {product} {location}"),
        (DemandSource.MARKETPLACE, f"{product} marketplace sellers buyers {location}"),
        (DemandSource.SOCIAL, f"{product} recommendations groups {location}"),
    )


def _city_base_score(city: str | None, rank: int, source: DemandSource) -> float:
    """Score one location/source pair with a simple local heuristic."""
    source_bonus = {
        DemandSource.SEARCH: 16.0,
        DemandSource.MARKETPLACE: 12.0,
        DemandSource.SOCIAL: 8.0,
    }[source]
    # City-specific targeting is usually more actionable than country-only targeting.
    city_bonus = 8.0 if city else 0.0
    return max(15.0, 92.0 - (rank * 3.5) + source_bonus + city_bonus)


def _build_signal(request: CampaignRequest, city: str | None, source: DemandSource, query: str, rank: int) -> CityDemandSignal:
    """Convert one query into a demand signal row."""
    score = min(100.0, _city_base_score(city, rank, source))
    return CityDemandSignal(
        product=request.product,
        region=request.region,
        city=city,
        source=source,
        query=query,
        search_url=_build_public_search_url(query),
        score=score,
        note="Free demand signal. Verify with real keyword volume before spending serious ad budget.",
        discovered_at=datetime.utcnow(),
    )


# ============================================
# Public adapter API - stable reusable surface
# Responsibility-order adapters are grouped by the job they do, not by install/start/stop lifecycle.
# Read them as: prepare inputs -> call the outside system -> map results back to app-safe data.
# ============================================
def fetch_city_demand_signals(request: CampaignRequest) -> list[CityDemandSignal]:
    """Build demand signals for the requested product and target locations."""
    signals: list[CityDemandSignal] = []
    for rank, city in enumerate(request.cities, start=1):
        signals.extend(
            _build_signal(request, city, source, query, rank)
            for source, query in _city_queries(request, city)
        )
    return sorted(signals, key=lambda item: item.score, reverse=True)
