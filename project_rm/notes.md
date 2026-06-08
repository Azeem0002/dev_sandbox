
"""
 Automated Patterns. Here's what you should NOT manually code:

 Pattern	        Library  	             What it automates
====================================================================================
- Retries	        tenacity	                Transient failures, backoff, jitter
- Logging	        loguru	                    File rotation, formatting, levels, context
- CLI parsing	    typer/click  	            Args, help text, validation, subcommands
- Background tasks	celery/apscheduler	        Async execution, job queues
- Rate limiting	    ratelimit	                API throttling, request limiting
- Caching	        cachetools/functools.lru_cache	     Expiring results, memoization
- Circuit breaker	pybreaker	                 Prevent cascading failures
- Timeouts	        timeout-decorator	         Prevent hanging operations
- Health checks	    health-check	             Service liveness monitoring
- Metrics	        prometheus_client	         Counters, gaugues, histograms
"""

### Layer Model for file structure

# usually adapter/ infrastructure
""" 
framework/IO/external-system code
adapters are boundaries that touches the outside world.
e.g db, cli, os service install, filesystem, HTTP or external libs/frameworks
"""

# orchestration/ application
"""
coordination of steps/use cases
e.g use cases, coordinates ports, transactions,
retries/workflow sequencing, returns app-level results

rules:
orchestration should accept already-cleaned input models or parse boundary input into models early
orchestration should return app-level results, not raw framework objects
orchestration does not have to only return “parsed data”; it can return domain results, status objects, or errors
"""


# core/domain/responsibility
"""
touches low level functions.
business meaning/rules
business rules, invariants, domain entities/value objects, policy decisions
"""
# Hexagonal rules
"""
core: decides
orchestration: coordinates
adapters: perform
cli: collects/displays
"""

# Common SQL Keywords
<!-- They're usually capitalized English words describing actions or conditions -->
SELECT, FROM, WHERE, INSERT, UPDATE, DELETE, 
CREATE, TABLE, INDEX, PRIMARY, KEY, NOT, NULL, 
DEFAULT, UNIQUE, TEXT, INTEGER, ORDER, BY, 
ASC, DESC, AND, OR, IN, LIKE, BETWEEN

# Reusable Adapter Checklist

+----------------------+------------------------------------------------------------------+
| Adapter              | 90-99% function order / responsibilities                         |
+----------------------+------------------------------------------------------------------+
| SQLite DB adapter    | get platform dir -> connection helper -> normalize/serialize  |
|                      | values for storage -> init schema -> cleanup/repair helpers      |
|                      | -> insert row(s) -> fetch one by id/name -> fetch many/list      |
|                      | -> update row(s) -> delete one row -> delete many rows           |
|                      | -> exists check -> count row(s) -> aggregate counts/status       |
|                      | summaries -> transaction helper when a use case spans multiple   |
|                      | writes -> maintenance helpers only when the app truly needs them |
+----------------------+------------------------------------------------------------------+
| Process adapter      | get platform dir -> get pid file path -> read pid file           |
|                      | -> get live process handle -> verify this is our managed         |
|                      | process -> write pid file -> remove pid file                     |
|                      | -> resolve active program pid -> spawn detached program          |
|                      | -> poll for startup proof / crash detection                      |
|                      | -> read interval/status hints from process if the app needs it   |
|                      | -> stop program process -> best-effort stale-pid cleanup         |
+----------------------+------------------------------------------------------------------+
| Runtime/env adapter  | get platform dirs -> read env overrides -> detect dev/prod env   |
|                      | -> resolve local timezone -> prepare runtime directories/files   |
|                      | -> return important runtime paths (logs, worker scripts, etc.)   |
|                      | -> configure logger                                              |
+----------------------+------------------------------------------------------------------+
| Platform adapter     | detect raw host platform -> normalize platform name to app       |
|                      | vocabulary -> expose one stable small set of platform names      |
+----------------------+------------------------------------------------------------------+
| Service adapter      | define service/task/timer names -> build service/task/timer      |
|                      | command text -> run OS command helper -> reload backend if       |
|                      | needed -> read service properties/status                         |
|                      | -> install service -> installed/enabled checks                   |
|                      | -> start service -> stop service                                 |
+----------------------+------------------------------------------------------------------+


# Exception Policy

### Use These By Default
===============================================================================
- `ValueError`
  - bad user input
  - malformed CLI/API/config values
  - wrong option combinations

- `ValidationError`
  - domain/business validation failed
  - input was structurally valid enough to parse, but not valid for the use case
  - example: unsafe path, invalid backup target, conflicting resume state

- `OSError`
  - filesystem / process / OS failure
  - path creation, file read/write, unlink, permission denied, disk full, missing file
  - keep this native inside low-level OS/file adapters when possible

- `RuntimeError`
  - operation failed at app/adapter level after making a higher-level decision
  - service install/start/stop failed
  - detached child failed to prove startup
  - unsupported platform for a supported app operation


### Layer Rule
===============================================================================
- boundary / CLI
  - catch and present user-friendly output

- validation / parsing
  - prefer `ValueError` or `ValidationError`

- application / orchestration
  - translate only when it adds business/app meaning
  - do not wrap unexpected errors just to rename them

- low-level adapters
  - preserve native low-level exceptions when they are already meaningful
  - example: keep `OSError` for filesystem/process operations


### Quick Rule of Thumb
===============================================================================
- bad input -> `ValueError`
- business rule failed -> `ValidationError`
- OS/file/process failed -> `OSError`
- higher-level operation failed -> `RuntimeError`


# Naming Rules

### Function Naming
===============================================================================
- `get_*`
  - read/query only
  - should not mutate state or create files/directories
  - examples: `get_db_path`, `get_process`, `get_scheduler_status`

- `setup_*`
  - may create/init runtime state
  - examples: log dirs, logger sinks, app-owned folders

- `init_*`
  - bootstrap or initialize a subsystem/schema/runtime backend
  - usually allowed to mutate

- `ensure_*`
  - allowed to create/fix state so an invariant becomes true
  - use this name when side effects are intentional and required

- `build_*`
  - pure construction only
  - should return a value/text/object without mutating external state

- `parse_*` / `normalize_*`
  - transform input into safer/canonical form
  - should usually stay pure

- `read_*`
  - read raw external state
  - no mutation

- `write_*`
  - explicit mutation/output

- `remove_*` / `delete_*`
  - explicit destructive mutation

- `spawn_*` / `start_*` / `stop_*`
  - lifecycle or process/service side effects are expected


### Quick Smell Check
===============================================================================
- if a `get_*` creates directories/files, rename it or move the side effect
- if a `build_*` runs commands or writes files, rename it or split it
- if a `setup_*` only returns a computed value with no setup, rename it
