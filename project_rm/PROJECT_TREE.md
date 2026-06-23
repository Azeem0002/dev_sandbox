# Reading Order

Use this order when learning or reviewing a project. It starts with vocabulary,
then input cleanup, then the decisions, then the I/O edges.

```text
README / PROJECT_COMMANDS
 ↓
models
 ↓
validation/parsing
 ↓
core services/rules
 ↓
adapters/infrastructure
 ↓
application use cases
 ↓
boundary entrypoints
 ↓
workers/background loops
 ↓
private helpers last
```

# General Project Tree

Use this as the shared mental map for projects in `project_rm`. Current projects are still mostly flat files, but this is the directory home each module should map to when a project grows.

```text
project_name/
├── boundary/ cli
│   ├── api.py
│   ├── controller.py
│   ├── main.py
│   ├── organizer.py
│   └── scheduler.py
├── validation/ parsers
│   └── validation.py
├── application/ app
│   └── application.py
├── models/
│   ├── models.py
│   ├── job_models.py
│   ├── lifecycle_models.py
│   └── config_models.py
├── core/
│   ├── organize_service.py
│   ├── backup_service.py
│   └── file_utils.py
├── adapters/
│   ├── ai_adapter.py
│   ├── browser_adapter.py
│   ├── database_adapter.py
│   ├── email_adapter.py
│   ├── export_adapter.py
│   ├── google_auth_adapter.py
│   ├── hosting_adapter.py
│   ├── job_adapter.py
│   ├── location_adapter.py
│   ├── platform_adapter.py
│   ├── process_adapter.py
│   ├── product_adapter.py
│   ├── runtime_adapter.py
│   ├── scheduler_adapter.py
│   ├── security_adapter.py
│   ├── service_adapter.py
│   ├── social_adapter.py
│   ├── source_adapter.py
│   ├── systemd_adapter.py
│   ├── task_scheduler_adapter.py
│   ├── trend_adapter.py
│   └── user_auth_adapter.py
├── workers/
│   ├── autoclear.py
│   └── scheduler_daemon.py
├── tests/
│   └── test_*.py
└── README.md
```

# Placement Rules

```text
boundary/     -> CLI, API, webhook, GUI entrypoints
validation/   -> raw input parsing, normalization, and cleanup
application/  -> public use cases; coordinates models, core, and adapters
models/       -> dataclasses, Pydantic models, enums, configs, lifecycle/status models
core/         -> pure business rules and deterministic domain logic
adapters/     -> DB, OS, files, network, email, logging, service/process I/O, AI APIs, schedulers
workers/      -> long-running loops or background executables
tests/        -> automated checks
```

# Module Function Order

Use semantic workflow order inside each module: group functions by what they mean
and place them in the order the logic unfolds. This is close to responsibility
order plus dependency order. A reader should meet the small building blocks
before the public function that uses them.

```text
1. constants
2. tiny pure helpers
3. parsers/normalizers
4. private I/O helpers
5. private mappers/factories/status builders
6. private orchestration helpers
7. public API wrappers/use cases
8. CLI/app entrypoint last
```

Do not move functions only to alphabetize them. Alphabetical order separates
related ideas and is worse for learning. Move functions when the mental workflow
gets clearer: parse -> clean -> decide -> save/execute -> present.

# Naming Decisions

```text
database_adapter.py:
  Keep under adapters for these MVPs. A database is external I/O, even when it is SQLite.
  If a project grows large, `persistence/` can become a sub-package, but the module is still an adapter by architecture.

service_adapter.py:
  Keep this name as the cross-platform facade for native service/task integration.
  It should choose the platform backend, then delegate to a platform-specific adapter.

systemd_adapter.py:
  Own Linux-only systemd unit text, systemctl calls, and systemd status parsing.
  Extract this when service_adapter starts mixing too much Linux detail with platform dispatch.

task_scheduler_adapter.py:
  Own Windows-only Task Scheduler command text and `schtasks` calls.
  Windows Task Scheduler can keep a program available after reboot/logon by launching it at user logon.

process_adapter.py:
  Owns direct detached-process/PID-file behavior.
  Linux and Windows both execute processes, but a process alone dies on logout/reboot.
  Use process_adapter for direct "start now" execution.
  Use service_adapter -> systemd_adapter/task_scheduler_adapter for "keep it available after reboot/logon".

security_adapter.py:
  Own password hashing, token creation, token verification, HMAC signing, and constant-time comparisons.
  Use argon2-cffi for password hashing in projects that support password login.
  Use hashlib/hmac/secrets from the Python standard library for HMAC signatures, token ids, webhook signatures,
  file integrity, or dedupe fingerprints when a full protocol library is not needed.
  Do not add hashlib to every project. Add a security_adapter only when the project handles users, passwords,
  signed tokens, API keys, webhook signatures, file integrity, or dedupe fingerprints.
  For production OAuth/JWT-heavy apps, prefer a maintained library such as Authlib or PyJWT instead of expanding
  hand-written token code.

models.py / *_models.py:
  Own data shapes only.
  Do not put backend-specific factory functions here unless they are pure generic constructors with no adapter meaning.
```

# Current Flat-File Mapping

```text
boundary:
  api.py
  controller.py
  main.py
  organizer.py
  scheduler.py

validation:
  validation.py

application:
  application.py

models:
  models.py
  job_models.py
  lifecycle_models.py
  config_models.py

core:
  organize_service.py
  backup_service.py
  file_utils.py

adapters:
  *_adapter.py
  runtime_adapter.py
  google_auth_adapter.py
  location_adapter.py
  systemd_adapter.py
  task_scheduler_adapter.py
  user_auth_adapter.py

workers:
  autoclear.py
  scheduler_daemon.py
```

# Adapter Reuse Rule

Adapters are reusable by shape, not by blindly copying every project-specific line:

```text
Reusable skeleton:
  imports
  private I/O helpers
  private mapping/status helpers
  public adapter API

Project-specific parts:
  app names
  paths
  model classes
  command names
  provider URLs
  platform/service names
  business-specific mapping rules
```
