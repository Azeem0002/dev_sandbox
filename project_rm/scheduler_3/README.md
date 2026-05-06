# Scheduler

## Purpose
Cross-platform job scheduler for one-time and weekly command execution.

## Boundary
- CLI entrypoint: `scheduler.py`
- Main commands: `add`, `list`, `start`, `stop`, `status`, `pause`, `resume`, `remove`, `install`

## Layer Map
- Boundary: `scheduler.py`
- Application: `application.py`
- Core/shared models: `job_models.py`, `lifecycle_models.py`
- Persistence: `database_adapter.py`
- External/OS adapters: `process_adapter.py`, `platform_adapter.py`, `service_adapter.py`, `runtime_support.py`

## Reusable Patterns
- Input validation and normalization at the boundary
- Timezone-aware scheduling
- PID file lifecycle management
- Background/foreground process split
- Explicit storage parsing vs storage serialization

## Flow
Input -> Validate -> Build job -> Persist -> Schedule -> Log -> Present

## High-Risk Areas
- Timezone conversion
- Command validation
- PID file staleness
- Duplicate job names
- Background process ownership

## Rules of Thumb
- Keep business meaning out of adapters
- Parse early, serialize late
- Ask APScheduler for trigger behavior instead of guessing
- Prefer one-job and many-jobs functions when return shapes differ

## Study Order
1. `job_models.py`
2. `scheduler.py`
3. `database_adapter.py`
4. `process_adapter.py`
5. `application.py`
