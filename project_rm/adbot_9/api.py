#!/usr/bin/env python3
"""FastAPI boundary for adbot_9."""

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

try:
    from .application import export_saved_campaign, get_campaign_history, recommend_campaign
    from .database_adapter import init_db
    from .runtime_adapter import setup_environment, setup_logger
    from .user_auth_adapter import require_authenticated_user
    from .validation import build_campaign_request
except ImportError:
    from application import export_saved_campaign, get_campaign_history, recommend_campaign
    from database_adapter import init_db
    from runtime_adapter import setup_environment, setup_logger
    from user_auth_adapter import require_authenticated_user
    from validation import build_campaign_request


class CampaignRecommendPayload(BaseModel):
    """HTTP request body for targeted campaign recommendation."""

    product: str
    region: str = "NG"
    cities: list[str] | None = None
    platform: str = "meta"
    goal: str = "sales"
    audience: str = "local buyers"
    daily_budget: float = 10.0
    max_locations: int = 5


app = FastAPI(title="adbot_9", version="0.1.0")


# ============================================
# API boundary - thin wrapper around orchestration
# ============================================
@app.on_event("startup")
def startup() -> None:
    """Prepare runtime logging and database before serving requests."""
    log_file = setup_environment()
    setup_logger(log_file)
    init_db()


def _signal_to_dict(item) -> dict:
    """Convert one demand signal model into API-safe JSON."""
    return {
        "product": item.product,
        "region": item.region,
        "city": item.city,
        "source": item.source.value,
        "query": item.query,
        "search_url": item.search_url,
        "score": item.score,
        "note": item.note,
        "discovered_at": item.discovered_at.isoformat(),
    }


def _creative_to_dict(item) -> dict:
    """Convert one ad creative model into API-safe JSON."""
    return {
        "platform": item.platform.value,
        "city": item.city,
        "headline": item.headline,
        "primary_text": item.primary_text,
        "call_to_action": item.call_to_action,
        "landing_page_hint": item.landing_page_hint,
    }


def _plan_to_dict(plan) -> dict:
    """Convert one campaign plan into API-safe JSON."""
    return {
        "id": plan.id,
        "product": plan.product,
        "region": plan.region,
        "platform": plan.platform.value,
        "goal": plan.goal.value,
        "audience": plan.audience,
        "daily_budget": plan.daily_budget,
        "created_at": plan.created_at.isoformat(),
        "demand_signals": [_signal_to_dict(item) for item in plan.demand_signals],
        "creatives": [_creative_to_dict(item) for item in plan.creatives],
        "manual_launch_note": "Review policy, landing page claims, targeting, and budget inside the ad platform before launch.",
    }


def _require_user(authorization: str | None) -> None:
    """Require login for paid/user-owned API actions."""
    try:
        require_authenticated_user(authorization)
    except ValueError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error


@app.get("/health")
def health() -> dict[str, str]:
    """Return a small liveness response."""
    return {"status": "ok"}


@app.post("/campaigns/recommend")
def recommend(payload: CampaignRecommendPayload, authorization: str | None = Header(default=None)) -> dict:
    """Recommend target locations and ad copy for one product."""
    try:
        _require_user(authorization)
        request = build_campaign_request(
            product=payload.product,
            region=payload.region,
            cities=payload.cities,
            platform=payload.platform,
            goal=payload.goal,
            audience=payload.audience,
            daily_budget=payload.daily_budget,
            max_locations=payload.max_locations,
        )
        return _plan_to_dict(recommend_campaign(request))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/campaigns/history")
def history(limit: int = 20, authorization: str | None = Header(default=None)) -> list[dict]:
    """Return recent saved campaign plans."""
    _require_user(authorization)
    return [_plan_to_dict(plan) for plan in get_campaign_history(limit)]


@app.get("/campaigns/{plan_id}/export")
def export(plan_id: str, authorization: str | None = Header(default=None)) -> dict:
    """Return copyable campaign notes for one saved campaign plan."""
    try:
        _require_user(authorization)
        exported = export_saved_campaign(plan_id)
        return {"plan_id": exported.plan_id, "created_at": exported.created_at.isoformat(), "content": exported.content}
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
