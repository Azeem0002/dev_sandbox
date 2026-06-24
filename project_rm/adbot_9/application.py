"""Application/orchestration layer for adbot_9."""

try:
    from .ai_adapter import generate_campaign_creatives
    from .database_adapter import fetch_campaign_plan, fetch_recent_campaign_plans, insert_campaign_plan
    from .demand_adapter import fetch_city_demand_signals
    from .export_adapter import export_campaign_plan
    from .models import CampaignPlan, CampaignRequest, ExportedCampaign
except ImportError:
    from ai_adapter import generate_campaign_creatives
    from database_adapter import fetch_campaign_plan, fetch_recent_campaign_plans, insert_campaign_plan
    from demand_adapter import fetch_city_demand_signals
    from export_adapter import export_campaign_plan
    from models import CampaignPlan, CampaignRequest, ExportedCampaign


# ============================================
# Application / Orchestration - Public use cases
# Start reading internals from here.
# ============================================
def recommend_campaign(request: CampaignRequest) -> CampaignPlan:
    """
    Build and save a targeted ad campaign plan.

    Flow:
        POST /campaigns/recommend -> build_campaign_request -> recommend_campaign
        recommend_campaign
            -> fetch_city_demand_signals
            -> generate_campaign_creatives
            -> insert_campaign_plan
    """
    signals = fetch_city_demand_signals(request)[: request.max_locations * 3]
    creatives = generate_campaign_creatives(request, signals)
    plan = CampaignPlan(
        product=request.product,
        region=request.region,
        platform=request.platform,
        goal=request.goal,
        audience=request.audience,
        daily_budget=request.daily_budget,
        demand_signals=signals,
        creatives=creatives,
    )
    return insert_campaign_plan(plan)


def get_campaign_history(limit: int = 20) -> list[CampaignPlan]:
    """
    Return recent saved campaign plans.

    Flow:
        GET /campaigns/history -> get_campaign_history
        get_campaign_history
            -> fetch_recent_campaign_plans
    """
    return fetch_recent_campaign_plans(limit)


def export_saved_campaign(plan_id: str) -> ExportedCampaign:
    """
    Return copyable export text for one saved campaign plan.

    Flow:
        GET /campaigns/{plan_id}/export -> export_saved_campaign
        export_saved_campaign
            -> fetch_campaign_plan
            -> export_campaign_plan
    """
    plan = fetch_campaign_plan(plan_id)
    if plan is None:
        raise ValueError("Campaign plan not found")
    return export_campaign_plan(plan)
