# Autoclear

## Purpose
Cross-platform terminal autoclear worker with process and system service support.

## Boundary
- CLI entrypoint: `controller.py`
- Worker entrypoint: `autoclear.py`

## Layer Map
- Boundary: `controller.py`
- Application: `application.py`
- Core/worker logic: `autoclear.py`, `lifecycle_models.py`
- External/OS adapters: `process_adapter.py`, `platform_adapter.py`, `service_adapter.py`, `systemd_adapter.py`, `task_scheduler_adapter.py`, `runtime_adapter.py`

## Reusable Patterns
- Human interval parsing
- PID file lifecycle management
- Detached process startup
- Service-vs-process backend selection
- Environment-aware status display

## Flow
Input -> Validate interval -> Detect platform -> Start/stop/status backend -> Log -> Present

## High-Risk Areas
- PID file staleness
- Service/process backend drift
- Broken interval parsing
- Permission errors in user data/state dirs

## Rules of Thumb
- Keep worker loop separate from control plane
- Let application choose backend, not the CLI
- Keep process adapter responsible only for process lifecycle

## Study Order
1. `autoclear.py`
2. `application.py`
3. `process_adapter.py`
4. `service_adapter.py`
5. `systemd_adapter.py`
6. `task_scheduler_adapter.py`
7. `controller.py`

## Developer Contact

For reviews, custom automation, or partnership discussions, show the developer contact in the product/docs through configurable values:

```text
Email: DEV_CONTACT_EMAIL
WhatsApp: DEV_CONTACT_WHATSAPP
```
