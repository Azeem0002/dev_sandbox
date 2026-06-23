# Project Commands

Run these commands from the project folder while using the shared root uv environment:

```bash
cd /home/az/dev_sandbox/project_rm
```

## Learning Map

Use this order for every project:

1. Core vocabulary: `models.py`, `*_models.py`
2. Validation/parsing: `validation.py`
3. App/Application/orchestration: `application.py`
4. Adapters/infrastructure: `*_adapter.py`, `runtime_adapter.py`
5. Boundary/entrypoints: `organizer.py`, `controller.py`, `scheduler.py`, `scraper.py`, `api.py`

See `PROJECT_TREE.md` for the recommended module directories when a project grows past flat files.

## Hosting Map

Use `hosting_adapter.py` for deployable API projects and always-on worker
projects. Local OS-only tools use `process_adapter.py` or `service_adapter.py`
instead.

Micro-SaaS backend decision:

```text
Each deployable product should expose one unified backend that can run locally
or on a cloud server. Web, mobile, and desktop frontends should call that same
backend API without backend rewrites. Keep frontend clients platform-specific
only at the UI layer.
```

User-auth decision:

```text
secure_login_5     -> reusable Google/password login and JWT sessions
partner_match_8    -> owns its own Google login because the social profile is product-specific
scraper_4 API      -> requires secure_login_5 bearer token for useful endpoints
media_automation_6 -> requires secure_login_5 bearer token for useful endpoints
lead_finder_7      -> requires secure_login_5 bearer token for useful endpoints
local OS tools     -> no login until they expose a real multi-user API
```

```text
organizer_1        -> local CLI/file utility
autoclear_2        -> local OS utility
scheduler_3        -> host on VPS/server as always-on worker, not laptop-only
scraper_4          -> optional API; recurring scraping is better as cron/GitHub Actions/VPS work
secure_login_5     -> host as API when real users need login/session access
media_automation_6 -> host on an always-on server or pair API with an external scheduler
lead_finder_7      -> host as API when buyers/sellers should be searched remotely
partner_match_8    -> host as one API backend for web/mobile/desktop partner discovery clients
```

## Organizer

```bash
uv run --project .. python organizer_1/organizer.py --help
uv run --project .. python organizer_1/organizer.py analyze /path/to/folder
uv run --project .. python organizer_1/organizer.py organize /path/to/folder
uv run --project .. python organizer_1/organizer.py backup /path/to/folder --list
```

## Autoclear

```bash
uv run --project .. python autoclear_2/controller.py --help
uv run --project .. python autoclear_2/controller.py status
uv run --project .. python autoclear_2/controller.py start --interval 1m
uv run --project .. python autoclear_2/controller.py stop
uv run --project .. python autoclear_2/autoclear.py --once
```

## Scheduler

```bash
uv run --project .. python scheduler_3/scheduler.py --help
uv run --project .. python scheduler_3/scheduler.py add --interactive
uv run --project .. python scheduler_3/scheduler.py list
uv run --project .. python scheduler_3/scheduler.py status
uv run --project .. python scheduler_3/scheduler.py start
uv run --project .. python scheduler_3/scheduler.py stop
uv run --project .. python -c "from scheduler_3.hosting_adapter import get_hosting_profile, build_host_command; print(get_hosting_profile()); print(build_host_command())"
```

Command validation note:

```bash
uv run --project .. python scheduler_3/scheduler.py add --name "Bad" --command "proj" --type weekly --days 1 --time 09:00
```

## Scraper 4

```bash
uv run --project .. python scraper_4/scraper.py --help
uv run --project .. python scraper_4/scraper.py research --interactive
uv run --project .. python scraper_4/scraper.py trends --mode products --keyword laptop --region US --export csv
uv run --project .. python scraper_4/scraper.py trends --mode products --region NG --broad-source exploratory --export csv
uv run --project .. python scraper_4/scraper.py trends --mode jobs --keyword python --region NG --export json
uv run --project .. python scraper_4/scraper.py trends --mode jobs --keyword python --region NG --city Lagos --export json
uv run --project .. python scraper_4/scraper.py recent-jobs --region NG --max-age-hours 3d
uv run --project .. python scraper_4/scraper.py notify-products --keyword phone --region NG
uv run --project .. python scraper_4/scraper.py arbitrage --source-cost 12000 --sell-price 20000 --shipping-cost 1500 --platform-fee 1000 --ad-cost 2000
uv run --project .. python scraper_4/scraper.py history
```

Optional API boundary:

```bash
uv run --project .. uvicorn scraper_4.api:app --reload
uv run --project .. python -c "from scraper_4.hosting_adapter import get_hosting_profile, build_host_command; print(get_hosting_profile()); print(build_host_command())"
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/trends -H "Authorization: Bearer TOKEN_HERE" -H "Content-Type: application/json" -d '{"mode":"products","keyword":"laptop","region":"US","city":"New York","max_results":5}'
curl -X POST http://127.0.0.1:8000/scrape -H "Authorization: Bearer TOKEN_HERE" -H "Content-Type: application/json" -d '{"url":"https://example.com","mode":"products","max_results":5}'
```

## Secure Login 5

API entrypoint:

```bash
uv run --project .. uvicorn secure_login_5.api:app --reload
uv run --project .. python -c "from secure_login_5.hosting_adapter import get_hosting_profile, build_host_command; print(get_hosting_profile()); print(build_host_command())"
```

Common checks:

```bash
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/register -H "Content-Type: application/json" -d '{"email":"az@example.com","password":"Password123"}'
curl -X POST http://127.0.0.1:8000/login -H "Content-Type: application/json" -d '{"email":"az@example.com","password":"Password123"}'
curl -X POST http://127.0.0.1:8000/auth/google -H "Content-Type: application/json" -d '{"id_token":"dev:az@example.com"}'
curl http://127.0.0.1:8000/me -H "Authorization: Bearer TOKEN_HERE"
```

## Media Automation 6

API entrypoint:

```bash
uv run --project .. uvicorn media_automation_6.api:app --reload
uv run --project .. python -c "from media_automation_6.hosting_adapter import get_hosting_profile, build_host_command; print(get_hosting_profile()); print(build_host_command())"
```

Common checks:

```bash
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/generate -H "Authorization: Bearer TOKEN_HERE" -H "Content-Type: application/json" -d '{"topic":"AI tools for solo developers","platform":"linkedin","tone":"practical","audience":"solo founders","goal":"teach one useful lesson"}'
curl -X POST http://127.0.0.1:8000/posts -H "Authorization: Bearer TOKEN_HERE" -H "Content-Type: application/json" -d '{"topic":"AI tools for solo developers","platform":"linkedin","tone":"practical","audience":"solo founders","goal":"teach one useful lesson"}'
curl -X POST http://127.0.0.1:8000/automation/start -H "Authorization: Bearer TOKEN_HERE" -H "Content-Type: application/json" -d '{"interval_minutes":"30m","dry_run":true}'
curl http://127.0.0.1:8000/automation/status -H "Authorization: Bearer TOKEN_HERE"
```

## Lead Finder 7

API entrypoint:

```bash
uv run --project .. uvicorn lead_finder_7.api:app --reload
uv run --project .. python -c "from lead_finder_7.hosting_adapter import get_hosting_profile, build_host_command; print(get_hosting_profile()); print(build_host_command())"
```

Common checks:

```bash
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/leads -H "Authorization: Bearer TOKEN_HERE" -H "Content-Type: application/json" -d '{"product":"phone accessories","region":"NG","city":"Lagos","intent":"both","max_results":6}'
curl http://127.0.0.1:8000/history -H "Authorization: Bearer TOKEN_HERE"
```

## Partner Match 8

API entrypoint:

```bash
uv run --project .. uvicorn partner_match_8.api:app --reload
uv run --project .. python -c "from partner_match_8.hosting_adapter import get_hosting_profile, build_host_command; print(get_hosting_profile()); print(build_host_command())"
```

Common checks:

```bash
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/auth/google -H "Content-Type: application/json" -d '{"id_token":"dev:az@example.com"}'
curl http://127.0.0.1:8000/me -H "Authorization: Bearer TOKEN_HERE"
curl -X PUT http://127.0.0.1:8000/me/username -H "Authorization: Bearer TOKEN_HERE" -H "Content-Type: application/json" -d '{"username":"az_builder"}'
curl -X PUT http://127.0.0.1:8000/me/profile -H "Authorization: Bearer TOKEN_HERE" -H "Content-Type: application/json" -d '{"display_name":"Az","bio":"Building practical SaaS tools","mindset_tags":["builder","automation"],"goal_tags":["programming","business"],"sub_goal_tags":["backend programming","ai automation"],"availability":"open_to_partner","looking_for":"nearby serious partners"}'
curl -X PUT http://127.0.0.1:8000/me/location -H "Authorization: Bearer TOKEN_HERE" -H "Content-Type: application/json" -d '{"latitude":6.5244,"longitude":3.3792,"city":"Lagos","is_enabled":true}'
curl http://127.0.0.1:8000/partners/nearby -H "Authorization: Bearer TOKEN_HERE"
curl "http://127.0.0.1:8000/partners/nearby?radius_km=10" -H "Authorization: Bearer TOKEN_HERE"
curl -X POST http://127.0.0.1:8000/posts -H "Authorization: Bearer TOKEN_HERE" -H "Content-Type: application/json" -d '{"post_type":"building","body":"Building a partner locator MVP","media_urls":["https://example.com/demo.png"],"tags":["programming","startup"]}'
curl http://127.0.0.1:8000/feed -H "Authorization: Bearer TOKEN_HERE"
curl -X POST http://127.0.0.1:8000/posts/POST_ID/likes -H "Authorization: Bearer TOKEN_HERE"
curl -X POST http://127.0.0.1:8000/posts/POST_ID/comments -H "Authorization: Bearer TOKEN_HERE" -H "Content-Type: application/json" -d '{"body":"This is useful."}'
curl http://127.0.0.1:8000/posts/POST_ID/comments -H "Authorization: Bearer TOKEN_HERE"
curl -X POST http://127.0.0.1:8000/users/USER_ID/follow -H "Authorization: Bearer TOKEN_HERE"
curl -X POST http://127.0.0.1:8000/partner-requests -H "Authorization: Bearer TOKEN_HERE" -H "Content-Type: application/json" -d '{"receiver_user_id":"USER_ID","message":"Want to build together?"}'
curl http://127.0.0.1:8000/partner-requests -H "Authorization: Bearer TOKEN_HERE"
curl http://127.0.0.1:8000/notifications -H "Authorization: Bearer TOKEN_HERE"
curl http://127.0.0.1:8000/profiles/USER_ID -H "Authorization: Bearer TOKEN_HERE"
curl http://127.0.0.1:8000/me/profile-visits -H "Authorization: Bearer TOKEN_HERE"
curl -X POST http://127.0.0.1:8000/reports -H "Authorization: Bearer TOKEN_HERE" -H "Content-Type: application/json" -d '{"target_type":"post","target_id":"POST_ID","reason":"spam","details":"Promotional spam"}'
curl -X POST http://127.0.0.1:8000/reports -H "Authorization: Bearer TOKEN_HERE" -H "Content-Type: application/json" -d '{"target_type":"comment","target_id":"COMMENT_ID","reason":"abuse","details":"Abusive comment"}'
curl -X POST http://127.0.0.1:8000/groups -H "Authorization: Bearer TOKEN_HERE" -H "Content-Type: application/json" -d '{"name":"Builders","purpose":"ship useful SaaS tools"}'
curl -X POST http://127.0.0.1:8000/groups/GROUP_ID/invites -H "Authorization: Bearer TOKEN_HERE" -H "Content-Type: application/json" -d '{"expires_in_hours":72}'
curl -X POST http://127.0.0.1:8000/groups/invites/INVITE_TOKEN/join -H "Authorization: Bearer TOKEN_HERE"
curl -X POST http://127.0.0.1:8000/safety/blocks -H "Authorization: Bearer TOKEN_HERE" -H "Content-Type: application/json" -d '{"blocked_user_id":"USER_ID"}'
```

Developer contact placeholders used across project READMEs:

```text
Email: DEV_CONTACT_EMAIL
WhatsApp: DEV_CONTACT_WHATSAPP
```
