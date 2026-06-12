"""Validation/parsing helpers for lead_finder_7."""

try:
    from .models import LeadIntent, LeadSearchRequest
except ImportError:
    from models import LeadIntent, LeadSearchRequest


SUPPORTED_REGIONS = {"US", "GB", "NG", "CA", "AU", "IN", "ZA", "GH", "KE"}
REGION_ALIASES = {"UK": "GB"}


def normalize_product(value: str) -> str:
    """Normalize a product keyword and reject empty/unsafe input."""
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned:
        raise ValueError("Product cannot be empty")
    if len(cleaned) > 100:
        raise ValueError("Product must be 100 characters or less")
    if not any(char.isalnum() for char in cleaned):
        raise ValueError("Product must include at least one letter or number")
    return cleaned


def normalize_region(value: str) -> str:
    """Normalize region into an uppercase country code."""
    cleaned = value.strip().upper() if isinstance(value, str) else ""
    cleaned = REGION_ALIASES.get(cleaned, cleaned)
    if cleaned not in SUPPORTED_REGIONS:
        raise ValueError(f"Unsupported region '{cleaned}'. Add it to SUPPORTED_REGIONS first.")
    return cleaned


def parse_lead_intent(value: str) -> LeadIntent:
    """Parse user/API text into a supported lead intent."""
    return LeadIntent(value.strip().lower())


def normalize_max_results(value: int) -> int:
    """Clamp result count to a practical MVP range."""
    if value < 1:
        raise ValueError("max_results must be at least 1")
    if value > 50:
        raise ValueError("max_results must be 50 or less")
    return value


def build_lead_search_request(*, product: str, region: str, intent: str, max_results: int) -> LeadSearchRequest:
    """Build clean lead-search input from raw boundary values."""
    return LeadSearchRequest(
        product=normalize_product(product),
        region=normalize_region(region),
        intent=parse_lead_intent(intent),
        max_results=normalize_max_results(max_results),
    )
