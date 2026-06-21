"""Public lead-source adapter for lead_finder_7.

This adapter builds inspection targets from public web/search surfaces. It does
not spam, DM, or bypass platform rules. A human can inspect/export the leads.
"""

from __future__ import annotations

import urllib.parse
from datetime import datetime

try:
    from .models import LeadIntent, LeadSearchRequest, LeadSource, LeadTarget
except ImportError:
    from models import LeadIntent, LeadSearchRequest, LeadSource, LeadTarget


# ============================================
# Source adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================
def _build_public_search_url(query: str) -> str:
    """Build a public search URL a human can inspect."""
    return f"https://www.google.com/search?{urllib.parse.urlencode({'q': query})}"


def _intent_queries(request: LeadSearchRequest) -> tuple[tuple[LeadIntent, LeadSource, str], ...]:
    """Build buyer/seller discovery queries without hardcoded hidden products."""
    product = request.product
    location = f"{request.city} {request.region}" if request.city else request.region
    buyer_queries = (
        (LeadIntent.BUYERS, LeadSource.SEARCH, f'people looking to buy "{product}" {location}'),
        (LeadIntent.BUYERS, LeadSource.SOCIAL, f'"want to buy" "{product}" {location}'),
        (LeadIntent.BUYERS, LeadSource.MARKETPLACE, f'"buy {product}" marketplace {location}'),
    )
    seller_queries = (
        (LeadIntent.SELLERS, LeadSource.SEARCH, f'"{product}" supplier distributor {location}'),
        (LeadIntent.SELLERS, LeadSource.MARKETPLACE, f'"{product}" wholesale seller {location}'),
        (LeadIntent.SELLERS, LeadSource.SOCIAL, f'"selling {product}" {location}'),
    )
    if request.intent == LeadIntent.BUYERS:
        return buyer_queries
    if request.intent == LeadIntent.SELLERS:
        return seller_queries
    return buyer_queries + seller_queries


def _build_lead_target(product: str, region: str, city: str | None, intent: LeadIntent, source: LeadSource, query: str, rank: int) -> LeadTarget:
    """Convert one query into a lead target row."""
    return LeadTarget(
        product=product,
        region=region,
        city=city,
        intent=intent,
        source=source,
        title=query,
        url=_build_public_search_url(query),
        score=max(10.0, 100.0 - ((rank - 1) * 8.0)),
        note="Public search target. Inspect manually before outreach.",
        discovered_at=datetime.utcnow(),
    )


# ============================================
# Public adapter API - stable reusable surface
# ============================================
def fetch_public_lead_targets(request: LeadSearchRequest) -> list[LeadTarget]:
    """Build public buyer/seller lead targets for one product and region."""
    return [
        _build_lead_target(request.product, request.region, request.city, intent, source, query, index)
        for index, (intent, source, query) in enumerate(_intent_queries(request), start=1)
    ][:request.max_results]
