#!/usr/bin/env python3
"""FastAPI boundary for lead_finder_7."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

try:
    from .application import find_leads, get_history
    from .database_adapter import init_db
    from .runtime_support import setup_environment, setup_logger
    from .validation import build_lead_search_request
except ImportError:
    from application import find_leads, get_history
    from database_adapter import init_db
    from runtime_support import setup_environment, setup_logger
    from validation import build_lead_search_request


class LeadSearchPayload(BaseModel):
    """HTTP request body for buyer/seller lead discovery."""
    product: str
    region: str = "US"
    intent: str = "both"
    max_results: int = 10


app = FastAPI(title="lead_finder_7", version="0.1.0")


# ============================================
# API boundary - thin wrapper around orchestration
# ============================================
@app.on_event("startup")
def startup() -> None:
    """Prepare runtime logging and database before serving requests."""
    log_file = setup_environment()
    setup_logger(log_file)
    init_db()


def _lead_to_dict(item) -> dict:
    """Convert one lead model into API-safe JSON."""
    return {
        "product": item.product,
        "region": item.region,
        "intent": item.intent.value,
        "source": item.source.value,
        "title": item.title,
        "url": item.url,
        "score": item.score,
        "note": item.note,
        "discovered_at": item.discovered_at.isoformat(),
    }


def _run_to_dict(run) -> dict:
    """Convert one lead run into API-safe JSON."""
    return {
        "product": run.product,
        "region": run.region,
        "intent": run.intent.value,
        "created_at": run.created_at.isoformat(),
        "leads": [_lead_to_dict(item) for item in run.leads],
    }


@app.get("/health")
def health() -> dict[str, str]:
    """Return a small liveness response."""
    return {"status": "ok"}


@app.post("/leads")
def leads(payload: LeadSearchPayload) -> dict:
    """Find buyer/seller lead targets for one product."""
    try:
        request = build_lead_search_request(
            product=payload.product,
            region=payload.region,
            intent=payload.intent,
            max_results=payload.max_results,
        )
        return _run_to_dict(find_leads(request))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/history")
def history(limit: int = 20) -> list[dict]:
    """Return recent saved lead runs."""
    return [_run_to_dict(run) for run in get_history(limit)]
