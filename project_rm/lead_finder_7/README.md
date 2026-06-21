# Lead Finder 7

FastAPI MVP for finding buyer/seller lead targets for a specific product.

## Why This Is Project 7

I chose this before an ad bot because it is safer and more monetizable:

- Lead finding can become a micro-SaaS.
- It helps buyers and sellers without violating ad/platform rules.
- It can later connect to scraper, email alerts, CRM, or manual outreach.
- An ad bot is more policy-risky and should be project 8 only after the lead engine is solid.

## Architecture

Read in this order:

1. `models.py`
2. `validation.py`
3. `application.py`
4. `source_adapter.py`
5. `ai_adapter.py`
6. `database_adapter.py`
7. `runtime_adapter.py`
8. `api.py`

## Commands

```bash
uv run --project .. uvicorn lead_finder_7.api:app --reload
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/leads -H "Content-Type: application/json" -d '{"product":"phone accessories","region":"NG","intent":"both","max_results":6}'
curl http://127.0.0.1:8000/history
```

## Safety Rule

This project finds lead targets. It does not automate spam outreach. Real outreach should be manual or permission-based until you have clear platform/API compliance.

## Developer Contact

For reviews, custom lead workflows, or partnership discussions, show the developer contact in the product/docs through configurable values:

```text
Email: DEV_CONTACT_EMAIL
WhatsApp: DEV_CONTACT_WHATSAPP
```
