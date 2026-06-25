"""AI/copy adapter for adbot_9.

Free MVP stance: generate deterministic campaign copy first. A paid LLM can
replace this adapter later without changing application use-cases.
"""

try:
    from .models import AdCreative, AdPlatform, CampaignGoal, CampaignRequest, CityDemandSignal
except ImportError:
    from models import AdCreative, AdPlatform, CampaignGoal, CampaignRequest, CityDemandSignal


# ============================================
# AI adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================
def _platform_cta(platform: AdPlatform, goal: CampaignGoal) -> str:
    """Return a practical call-to-action for one platform and goal."""
    if platform == AdPlatform.WHATSAPP:
        return "Message on WhatsApp"
    if goal == CampaignGoal.LEADS:
        return "Get quote"
    if goal == CampaignGoal.SALES:
        return "Shop now"
    if goal == CampaignGoal.RETARGETING:
        return "See offer"
    return "Learn more"


def _platform_headline_limit(platform: AdPlatform) -> int:
    """Return a safe headline length for one ad platform."""
    return 30 if platform == AdPlatform.GOOGLE else 48


def _trim(text: str, limit: int) -> str:
    """Trim generated text to a platform-safe length."""
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _location_text(signal: CityDemandSignal) -> str:
    """Return a readable location phrase for ad copy."""
    return signal.city or signal.region


def _angle_for_goal(goal: CampaignGoal) -> str:
    """Return the main message angle for one campaign goal."""
    if goal == CampaignGoal.LEADS:
        return "fast local help"
    if goal == CampaignGoal.SALES:
        return "available now with clear pricing"
    if goal == CampaignGoal.RETARGETING:
        return "the option worth coming back to"
    return "a practical option people are already searching for"


def _build_headline(request: CampaignRequest, signal: CityDemandSignal) -> str:
    """Build one short platform headline."""
    text = f"{request.product} in {_location_text(signal)}"
    return _trim(text, _platform_headline_limit(request.platform))


def _build_primary_text(request: CampaignRequest, signal: CityDemandSignal) -> str:
    """Build one primary ad text body."""
    return (
        f"People around {_location_text(signal)} are showing demand for {request.product}. "
        f"Position your offer as {_angle_for_goal(request.goal)} for {request.audience}. "
        "Use a clear landing page, proof, price/benefit, and one direct next step."
    )


def _build_landing_page_hint(request: CampaignRequest, signal: CityDemandSignal) -> str:
    """Suggest what the landing page should prove before traffic is sent."""
    return (
        f"Landing page should mention {_location_text(signal)}, show the {request.product} offer, "
        "include proof, answer price/delivery questions, and collect one simple action."
    )


def _build_creative(request: CampaignRequest, signal: CityDemandSignal) -> AdCreative:
    """Convert one demand signal into one campaign creative."""
    return AdCreative(
        platform=request.platform,
        city=signal.city,
        headline=_build_headline(request, signal),
        primary_text=_build_primary_text(request, signal),
        call_to_action=_platform_cta(request.platform, request.goal),
        landing_page_hint=_build_landing_page_hint(request, signal),
    )


# ============================================
# Public adapter API - stable reusable surface
# Responsibility-order adapters are grouped by the job they do, not by install/start/stop lifecycle.
# Read them as: prepare inputs -> call the outside system -> map results back to app-safe data.
# ============================================
def generate_campaign_creatives(request: CampaignRequest, signals: list[CityDemandSignal]) -> list[AdCreative]:
    """Generate platform-ready ad drafts from the strongest demand signals."""
    seen_locations: set[str] = set()
    creatives: list[AdCreative] = []
    for signal in signals:
        location_key = signal.city or signal.region
        if location_key in seen_locations:
            continue
        seen_locations.add(location_key)
        creatives.append(_build_creative(request, signal))
        if len(creatives) >= request.max_locations:
            break
    return creatives
