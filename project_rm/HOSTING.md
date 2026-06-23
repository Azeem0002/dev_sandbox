# Hosting Guide

This file answers one question: which projects deserve a server, and what kind?

## Rule Of Thumb

Use a server when the project must be reachable from the public internet, serve
multiple users, receive webhooks, or run while your laptop is off.

Do not host local file/OS utilities just because they are Python projects.
Those belong on your machine or a VPS you control.

## Project Decisions

| Project | Host? | Recommended host shape | Why |
| --- | --- | --- | --- |
| `organizer_1` | No | Local CLI | It organizes local files. Hosting adds risk without value. |
| `autoclear_2` | No | Local process/service | It clears local machine state. Use `process_adapter.py`/`service_adapter.py`. |
| `scheduler_3` | Yes | VPS/server worker | It is a micro-SaaS scheduler, so it should run 24/7 under systemd or a server process manager. |
| `scraper_4` | Optional | API plus scheduled worker | The API can be hosted, but recurring scraping is better as cron, GitHub Actions, or VPS work. |
| `secure_login_5` | Yes | FastAPI web app | Login/session systems become useful when other apps/users can call them. |
| `media_automation_6` | Yes | Always-on API/worker | Social scheduling needs recurring checks while your laptop is off. |
| `lead_finder_7` | Yes/optional | FastAPI web app | Useful as a hosted micro-SaaS API once you want remote access or customers. |
| `partner_match_8` | Yes | FastAPI web app plus worker-ready infrastructure | Social discovery needs hosted auth, location matching, notifications, media handling, and moderation. |

## Real User Scale

For projects that handle users, SQLite is acceptable for local MVPs, demos, and
solo internal tools. It is not the target for 5,000-10,000 concurrent users.

Use this production shape before selling a multi-user product seriously:

- FastAPI served by multiple workers behind a reverse proxy or managed app host.
- Managed Postgres for users, sessions, posts, reports, jobs, and app data.
- Redis for queues, rate limits, presence, notification fanout, and short-lived cache.
- Object storage for uploaded images/videos instead of storing media on the app server.
- Background workers for email, push notifications, scraping, posting, and AI tasks.
- Observability: logs, metrics, error tracking, uptime checks, and database backups.

Free vs premium access is mostly enforced in code, but billing is usually handled
by a third-party provider such as Stripe, Lemon Squeezy, Paddle, RevenueCat, or
the mobile app stores. The app stores each user's plan/entitlements and checks
those entitlements before premium actions.

## Adapter Decision

`hosting_adapter.py` is the right adapter for deployable API projects and
always-on worker projects.

It stores deploy-time metadata:

- app name
- ASGI module path or worker entrypoint
- healthcheck path
- whether the project needs an always-on worker
- the standard `build_host_command()` output for the host/process manager

It should not contain business logic, scraping logic, authentication logic, or
job scheduling rules. For actual OS service install/start/stop, use
`service_adapter.py`; for PID/process control, use `process_adapter.py`.
