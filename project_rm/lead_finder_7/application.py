"""Application/orchestration layer for lead_finder_7."""

try:
    from .ai_adapter import rank_leads
    from .database_adapter import fetch_recent_runs, insert_lead_run
    from .models import LeadRun, LeadSearchRequest
    from .source_adapter import fetch_public_lead_targets
except ImportError:
    from ai_adapter import rank_leads
    from database_adapter import fetch_recent_runs, insert_lead_run
    from models import LeadRun, LeadSearchRequest
    from source_adapter import fetch_public_lead_targets


# ============================================
# Application / Orchestration - Public use cases
# Start reading internals from here.
# ============================================
def find_leads(request: LeadSearchRequest) -> LeadRun:
    """
    Find and save buyer/seller lead targets for one product.

    Flow:
        POST /leads -> build_lead_search_request -> find_leads
        find_leads
            -> fetch_public_lead_targets
            -> rank_leads
            -> insert_lead_run
    """
    targets = fetch_public_lead_targets(request)
    ranked = rank_leads(targets)[:request.max_results]
    run = LeadRun(product=request.product, region=request.region, city=request.city, intent=request.intent, leads=ranked)
    return insert_lead_run(run)


def get_history(limit: int = 20) -> list[LeadRun]:
    """
    Return recent saved lead runs.

    Flow:
        GET /history -> get_history
        get_history
            -> fetch_recent_runs
    """
    return fetch_recent_runs(limit)
