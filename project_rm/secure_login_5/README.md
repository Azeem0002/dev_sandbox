# Secure Login 5

FastAPI JWT authentication MVP with DTOs, server-side sessions, SQLite, and reusable adapter structure.

## Architecture

Read in this order:

1. `models.py`
2. `validation.py`
3. `application.py`
4. `security_adapter.py`
5. `database_adapter.py`
6. `runtime_adapter.py`
7. `api.py`

## Commands

```bash
uv run --project .. uvicorn secure_login_5.api:app --reload
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/register -H "Content-Type: application/json" -d '{"email":"az@example.com","password":"Password123"}'
curl -X POST http://127.0.0.1:8000/login -H "Content-Type: application/json" -d '{"email":"az@example.com","password":"Password123"}'
```

## Production Notes

Set a real secret before deployment:

```bash
export SECURE_LOGIN_JWT_SECRET="replace-with-long-random-secret"
```

For production, replace the stdlib JWT/PBKDF2 adapter with audited libraries when budget allows.

## Developer Contact

For reviews, auth integration help, or partnership discussions, show the developer contact in the product/docs through configurable values:

```text
Email: DEV_CONTACT_EMAIL
WhatsApp: DEV_CONTACT_WHATSAPP
```
