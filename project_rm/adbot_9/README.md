# AdBot 9

FastAPI MVP for planning targeted ads by product, region, and city.

## What It Does

AdBot checks transparent demand signals for a product across target cities, ranks the strongest locations, writes platform-ready ad copy, saves the campaign plan, and exports launch notes.

It does not auto-send ads in the MVP. That is intentional. Real ad sending needs platform approvals, billing controls, policy review, account permissions, conversion tracking, and abuse prevention.

## Best MVP Positioning

Build this as a targeted ads assistant:

1. Find where demand appears strongest.
2. Recommend city targeting.
3. Generate ad copy for Meta, Google, TikTok, or WhatsApp.
4. Export a manual launch plan.
5. Later connect official ad APIs after the strategy is proven.

## Architecture

Read in this order:

1. `models.py`
2. `validation.py`
3. `application.py`
4. `demand_adapter.py`
5. `ai_adapter.py`
6. `database_adapter.py`
7. `export_adapter.py`
8. `runtime_adapter.py`
9. `api.py`

## Commands

```bash
uv run --project .. uvicorn adbot_9.api:app --reload
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/campaigns/recommend -H "Authorization: Bearer TOKEN_HERE" -H "Content-Type: application/json" -d '{"product":"phone accessories","region":"NG","cities":["Lagos","Abuja"],"platform":"meta","goal":"sales","audience":"local smartphone users","daily_budget":20,"max_locations":3}'
curl http://127.0.0.1:8000/campaigns/history -H "Authorization: Bearer TOKEN_HERE"
curl http://127.0.0.1:8000/campaigns/PLAN_ID/export -H "Authorization: Bearer TOKEN_HERE"
```

## Production Upgrade Path

- Replace `demand_adapter.py` with Google Ads Keyword Planner, DataForSEO, Semrush, marketplaces, or internal search logs.
- Replace deterministic `ai_adapter.py` copy with a paid LLM only after the local template stops being enough.
- Replace SQLite with Postgres before selling this as a multi-user SaaS with heavy concurrent usage.
- Add Stripe for free/premium limits before connecting paid ad-platform actions.
- Connect Meta Marketing API, Google Ads API, TikTok Business API, or WhatsApp Business API only after policy and billing safeguards exist.

## Developer Contact

For reviews, custom ad workflows, or partnership discussions, show the developer contact in the product/docs through configurable values:

```text
Email: DEV_CONTACT_EMAIL
WhatsApp: DEV_CONTACT_WHATSAPP
```
