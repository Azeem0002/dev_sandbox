Hermes agent

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

# SQLite Database
- config/path helpers
- connection helper
- init schema
- insert row(s)
- fetch one by id/name
- fetch many/list
- update row(s)
- delete row(s)
- exists check
- count row(s)
- aggregate counts/status summaries
- transaction helper when a use case spans multiple writes
- maintenance helpers only when the app truly needs them

# process adapter
- get platform dir
- get pid file path
- read pid file
- is program process
- get process
- write pid file
- remove pid file
- get active program pid
- spawn detached program
- stop program process
- check program status
- restart program