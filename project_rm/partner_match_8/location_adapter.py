"""Location adapter for distance calculations and public distance labels."""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt


# ============================================
# Location adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================
def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate approximate distance between two coordinates using haversine."""
    radius_km = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * radius_km * asin(sqrt(a))


def _distance_label(distance_km: float) -> str:
    """Return a privacy-safe distance band instead of exact coordinates."""
    if distance_km < 1:
        return "within 1 km"
    if distance_km < 5:
        return "within 5 km"
    if distance_km < 25:
        return "within 25 km"
    return f"about {round(distance_km)} km away"


# ============================================
# Public adapter API - stable reusable surface
# Responsibility-order adapters are grouped by the job they do, not by install/start/stop lifecycle.
# Read them as: prepare inputs -> call the outside system -> map results back to app-safe data.
# ============================================
def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Public wrapper for distance calculation."""
    return _distance_km(lat1, lon1, lat2, lon2)


def distance_label(distance_km: float) -> str:
    """Public wrapper for privacy-safe distance labels."""
    return _distance_label(distance_km)
