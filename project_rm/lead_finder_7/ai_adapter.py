"""AI/scoring adapter for lead_finder_7.

Free MVP stance: use deterministic scoring and notes first. A paid LLM can
replace this adapter later without changing application use-cases.
"""

try:
    from .models import LeadIntent, LeadSource, LeadTarget
except ImportError:
    from models import LeadIntent, LeadSource, LeadTarget


# ============================================
# AI adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================
def _source_bonus(source: LeadSource) -> float:
    """Return confidence bonus by source type."""
    # Marketplace/supplier searches tend to be more commercial than generic social chatter.
    if source == LeadSource.MARKETPLACE:
        return 10.0
    if source == LeadSource.SEARCH:
        return 6.0
    return 2.0


def _intent_note(intent: LeadIntent) -> str:
    """Explain how a human should interpret the lead intent."""
    if intent == LeadIntent.BUYERS:
        return "Buyer lead: look for demand, comments, requests, and repeated pain points."
    if intent == LeadIntent.SELLERS:
        return "Seller lead: look for suppliers, inventory, pricing, and shipping reliability."
    return "Mixed lead: separate buyer demand from seller supply before acting."


def _score_lead(target: LeadTarget) -> float:
    """Score one target with a local heuristic."""
    product_bonus = 8.0 if target.product.casefold() in target.title.casefold() else 0.0
    return min(100.0, target.score + _source_bonus(target.source) + product_bonus)


def _enrich_lead(target: LeadTarget) -> LeadTarget:
    """Attach score and educational note to one lead target."""
    target.score = _score_lead(target)
    target.note = f"{_intent_note(target.intent)} Source={target.source.value}. Inspect manually; do not automate spam outreach."
    return target


# ============================================
# Public adapter API - stable reusable surface
# Responsibility-order adapters are grouped by the job they do, not by install/start/stop lifecycle.
# Read them as: prepare inputs -> call the outside system -> map results back to app-safe data.
# ============================================
def rank_leads(targets: list[LeadTarget]) -> list[LeadTarget]:
    """Score and sort lead targets strongest first."""
    return sorted((_enrich_lead(target) for target in targets), key=lambda item: item.score, reverse=True)
