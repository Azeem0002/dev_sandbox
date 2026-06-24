"""Validation/parsing helpers for adbot_9."""

try:
    from .models import AdPlatform, CampaignGoal, CampaignRequest
except ImportError:
    from models import AdPlatform, CampaignGoal, CampaignRequest


SUPPORTED_REGIONS = {"US", "GB", "NG", "CA", "AU", "IN", "ZA", "GH", "KE"}
REGION_ALIASES = {"UK": "GB"}
DEFAULT_CITIES_BY_REGION = {
    "NG": ("Lagos", "Abuja", "Port Harcourt", "Ibadan", "Kano"),
    "US": ("New York", "Los Angeles", "Chicago", "Houston", "Atlanta"),
    "GB": ("London", "Manchester", "Birmingham", "Leeds", "Glasgow"),
    "CA": ("Toronto", "Vancouver", "Montreal", "Calgary", "Ottawa"),
    "AU": ("Sydney", "Melbourne", "Brisbane", "Perth", "Adelaide"),
    "IN": ("Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Chennai"),
    "ZA": ("Johannesburg", "Cape Town", "Durban", "Pretoria", "Soweto"),
    "GH": ("Accra", "Kumasi", "Tamale", "Takoradi", "Tema"),
    "KE": ("Nairobi", "Mombasa", "Kisumu", "Nakuru", "Eldoret"),
}


def _normalize_required_text(value: str, field_name: str, *, max_length: int = 180) -> str:
    """Normalize required human text and reject empty/huge values early."""
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned:
        raise ValueError(f"{field_name} cannot be empty")
    if len(cleaned) > max_length:
        raise ValueError(f"{field_name} must be {max_length} characters or less")
    if not any(char.isalnum() for char in cleaned):
        raise ValueError(f"{field_name} must include at least one letter or number")
    return " ".join(cleaned.split())


def normalize_product(value: str) -> str:
    """Normalize the product or offer being advertised."""
    return _normalize_required_text(value, "Product", max_length=100)


def normalize_region(value: str) -> str:
    """Normalize region into an uppercase country code."""
    cleaned = value.strip().upper() if isinstance(value, str) else ""
    cleaned = REGION_ALIASES.get(cleaned, cleaned)
    if cleaned not in SUPPORTED_REGIONS:
        raise ValueError(f"Unsupported region '{cleaned}'. Add it to SUPPORTED_REGIONS first.")
    return cleaned


def normalize_optional_city(value: str | None) -> str | None:
    """Normalize one optional city name for focused local targeting."""
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > 80:
        raise ValueError("city must be 80 characters or less")
    if not any(char.isalpha() for char in cleaned):
        raise ValueError("city must include at least one letter")
    return " ".join(cleaned.split())


def normalize_cities(region: str, cities: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    """Normalize explicit cities or use transparent defaults for the region."""
    cleaned = tuple(city for city in (normalize_optional_city(item) for item in cities or ()) if city)
    if cleaned:
        # Keep order but remove duplicates so repeated city input does not skew scoring.
        return tuple(dict.fromkeys(cleaned))
    return DEFAULT_CITIES_BY_REGION[region]


def parse_ad_platform(value: str) -> AdPlatform:
    """Parse user/API text into a supported ad platform."""
    return AdPlatform(value.strip().lower())


def parse_campaign_goal(value: str) -> CampaignGoal:
    """Parse user/API text into a supported campaign goal."""
    return CampaignGoal(value.strip().lower())


def normalize_daily_budget(value: float | int) -> float:
    """Clamp daily ad budget to a practical MVP planning range."""
    try:
        budget = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("daily_budget must be a number") from error
    if budget < 1:
        raise ValueError("daily_budget must be at least 1")
    if budget > 100000:
        raise ValueError("daily_budget must be 100000 or less")
    return round(budget, 2)


def normalize_max_locations(value: int) -> int:
    """Clamp recommended target locations to a small action-ready list."""
    if value < 1:
        raise ValueError("max_locations must be at least 1")
    if value > 20:
        raise ValueError("max_locations must be 20 or less")
    return value


def build_campaign_request(
    *,
    product: str,
    region: str,
    platform: str,
    goal: str,
    audience: str,
    daily_budget: float,
    max_locations: int,
    cities: list[str] | tuple[str, ...] | None = None,
) -> CampaignRequest:
    """Build clean campaign-planning input from raw boundary values."""
    normalized_region = normalize_region(region)
    return CampaignRequest(
        product=normalize_product(product),
        region=normalized_region,
        cities=normalize_cities(normalized_region, cities),
        platform=parse_ad_platform(platform),
        goal=parse_campaign_goal(goal),
        audience=_normalize_required_text(audience, "Audience", max_length=160),
        daily_budget=normalize_daily_budget(daily_budget),
        max_locations=normalize_max_locations(max_locations),
    )
