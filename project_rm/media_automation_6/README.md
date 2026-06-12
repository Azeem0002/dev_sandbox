# Media Automation 6

FastAPI social media automation MVP for generating, scheduling, and publishing posts.

## Architecture

Read in this order:

1. `models.py`
2. `validation.py`
3. `application.py`
4. `ai_adapter.py`
5. `database_adapter.py`
6. `social_adapter.py`
7. `scheduler_adapter.py`
8. `runtime_support.py`
9. `api.py`

## MVP Decision

- FastAPI is the hosted boundary.
- SQLite is enough for one-user MVP persistence.
- Local AI-style generation avoids paid APIs.
- Dry-run publishing is default because real platform APIs need credentials and app approval.
- The in-process scheduler is fine for a VPS MVP; move to `scheduler_3`, cron, Celery, or a managed worker when reliability needs increase.

## Commands

```bash
uv run --project .. uvicorn media_automation_6.api:app --reload
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/generate -H "Content-Type: application/json" -d '{"topic":"AI tools for solo developers","platform":"linkedin","tone":"practical","audience":"solo founders","goal":"teach one useful lesson"}'
curl -X POST http://127.0.0.1:8000/posts -H "Content-Type: application/json" -d '{"topic":"AI tools for solo developers","platform":"linkedin","tone":"practical","audience":"solo founders","goal":"teach one useful lesson"}'
curl -X POST http://127.0.0.1:8000/automation/start -H "Content-Type: application/json" -d '{"interval_minutes":30,"dry_run":true}'
```
