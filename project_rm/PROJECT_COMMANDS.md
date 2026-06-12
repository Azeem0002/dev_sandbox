# Project Commands

Run these commands from the project folder while using the shared root uv environment:

```bash
cd /home/az/dev_sandbox/project_rm
```

## Learning Map

Use this order for every project:

1. Core vocabulary: `models.py`, `*_models.py`
2. Validation/parsing: `validation.py`
3. Application/orchestration: `application.py`
4. Adapters/infrastructure: `*_adapter.py`, `runtime_support.py`
5. Boundary/entrypoints: `organizer.py`, `controller.py`, `scheduler.py`, `scraper.py`, `api.py`

See `PROJECT_TREE.md` for the recommended module directories when a project grows past flat files.

## Hosting Map

Use `hosting_adapter.py` for deployable API projects and always-on worker
projects. Local OS-only tools use `process_adapter.py` or `service_adapter.py`
instead.

```text
secure_login_5     -> host as API when real users need login/session access
media_automation_6 -> host on an always-on server or pair API with an external scheduler
lead_finder_7      -> host as API when buyers/sellers should be searched remotely
scraper_4          -> optional API; recurring scraping is better as cron/GitHub Actions/VPS work
scheduler_3        -> host on VPS/server as always-on worker, not laptop-only
autoclear_2        -> local OS utility
organizer_1        -> local CLI/file utility
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
uv run --project .. python autoclear_2/controller.py start --interval 10s
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
uv run --project .. python scraper_4/scraper.py recent-jobs --region NG --max-age-hours 72
uv run --project .. python scraper_4/scraper.py notify-products --keyword phone --region NG
uv run --project .. python scraper_4/scraper.py arbitrage --source-cost 12000 --sell-price 20000 --shipping-cost 1500 --platform-fee 1000 --ad-cost 2000
uv run --project .. python scraper_4/scraper.py history
```

Optional API boundary:

```bash
uv run --project .. uvicorn scraper_4.api:app --reload
uv run --project .. python -c "from scraper_4.hosting_adapter import get_hosting_profile, build_host_command; print(get_hosting_profile()); print(build_host_command())"
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
curl -X POST http://127.0.0.1:8000/generate -H "Content-Type: application/json" -d '{"topic":"AI tools for solo developers","platform":"linkedin","tone":"practical","audience":"solo founders","goal":"teach one useful lesson"}'
curl -X POST http://127.0.0.1:8000/posts -H "Content-Type: application/json" -d '{"topic":"AI tools for solo developers","platform":"linkedin","tone":"practical","audience":"solo founders","goal":"teach one useful lesson"}'
curl -X POST http://127.0.0.1:8000/automation/start -H "Content-Type: application/json" -d '{"interval_minutes":30,"dry_run":true}'
curl http://127.0.0.1:8000/automation/status
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
curl -X POST http://127.0.0.1:8000/leads -H "Content-Type: application/json" -d '{"product":"phone accessories","region":"NG","intent":"both","max_results":6}'
curl http://127.0.0.1:8000/history
```
