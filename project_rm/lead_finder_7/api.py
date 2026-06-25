#!/usr/bin/env python3
"""FastAPI boundary for lead_finder_7."""

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

try:
    from .application import find_leads, get_history
    from .database_adapter import init_db
    from .interface_adapter import get_frontend_contract
    from .runtime_adapter import setup_environment, setup_logger
    from .user_auth_adapter import require_authenticated_user
    from .validation import build_lead_search_request
except ImportError:
    from application import find_leads, get_history
    from database_adapter import init_db
    from interface_adapter import get_frontend_contract
    from runtime_adapter import setup_environment, setup_logger
    from user_auth_adapter import require_authenticated_user
    from validation import build_lead_search_request


class LeadSearchPayload(BaseModel):
    """HTTP request body for buyer/seller lead discovery."""
    product: str
    region: str = "US"
    city: str | None = None
    intent: str = "both"
    max_results: int = 10


app = FastAPI(title="lead_finder_7", version="0.1.0")


# ============================================
# API boundary - thin wrapper around orchestration
# ============================================
# Boundary mental model:
# 1. FastAPI receives HTTP JSON and Authorization headers.
# 2. The boundary checks login before protected paid/user-owned work.
# 3. validation.py turns raw payload text into a clean LeadSearchRequest.
# 4. application.py finds/ranks/saves leads through adapters.
# 5. Mapper helpers convert dataclasses/enums/datetimes into JSON-safe dicts.
@app.on_event("startup")
def startup() -> None:
    """Prepare runtime logging and database before serving requests."""
    log_file = setup_environment()
    setup_logger(log_file)
    init_db()


def _lead_to_dict(item) -> dict:
    """Convert one lead model into API-safe JSON."""
    # Dataclasses can contain enums/datetimes that JSON cannot serialize by
    # itself. The boundary flattens them into plain strings/numbers.
    return {
        "product": item.product,
        "region": item.region,
        "city": item.city,
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
        "city": run.city,
        "intent": run.intent.value,
        "created_at": run.created_at.isoformat(),
        "leads": [_lead_to_dict(item) for item in run.leads],
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


@app.get("/frontend-contract")
def frontend_contract() -> dict:
    """Return the stable API handoff contract for web/mobile/desktop clients."""
    return get_frontend_contract()


@app.post("/leads")
def leads(payload: LeadSearchPayload, authorization: str | None = Header(default=None)) -> dict:
    """Find buyer/seller lead targets for one product."""
    try:
        # Raw HTTP body -> validated request model -> application use-case.
        # Keeping this sequence visible makes the project easy to trace.
        _require_user(authorization)
        request = build_lead_search_request(
            product=payload.product,
            region=payload.region,
            city=payload.city,
            intent=payload.intent,
            max_results=payload.max_results,
        )
        return _run_to_dict(find_leads(request))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/history")
def history(limit: int = 20, authorization: str | None = Header(default=None)) -> list[dict]:
    """Return recent saved lead runs."""
    _require_user(authorization)
    return [_run_to_dict(run) for run in get_history(limit)]
