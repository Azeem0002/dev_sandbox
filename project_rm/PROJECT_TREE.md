# Project Module Trees

These trees show the recommended directory home for each module when a project grows past the flat-file learning stage.

```text
boundary/     -> CLI, API, webhook, GUI entrypoints
validation/   -> raw input parsing and cleanup
application/  -> public use-cases that coordinate work  
core/         -> app vocabulary, DTOs, domain rules, pure logic
adapters/     -> DB, OS, files, network, email, logging, service/process I/O  ### external systems 
workers/      -> long-running loops or background executables
tests/        -> automated checks
```

## organizer_1

```text
organizer_1/
├── boundary/organizer.py
├── validation/validation.py
├── app/application.py
├── core/models.py, file_utils.py, organize_service.py, backup_service.py
├── adapters/runtime_support.py
└── README.md
```

## autoclear_2

```text
autoclear_2/
├── boundary/controller.py
├── app/application.py
├── core/lifecycle_models.py
├── adapters/platform_adapter.py, process_adapter.py, runtime_support.py, service_adapter.py
├── workers/autoclear.py
└── README.md
```

## scheduler_3

```text
scheduler_3/
├── boundary/scheduler.py
├── application/application.py
├── core/job_models.py, lifecycle_models.py
├── adapters/database_adapter.py, hosting_adapter.py, platform_adapter.py, process_adapter.py, runtime_support.py, service_adapter.py
├── workers/scheduler_daemon.py
└── README.md
```

## scraper_4

```text
scraper_4/
├── boundary/scraper.py, main.py, api.py
├── validation/validation.py
├── application/application.py
├── core/models.py, product_adapter.py
├── adapters/ai_adapter.py, browser_adapter.py, database_adapter.py, email_adapter.py, export_adapter.py, hosting_adapter.py, job_adapter.py, platform_adapter.py, runtime_support.py, trend_adapter.py
└── README.md
```

## media_automation_6

```text
media_automation_6/
├── boundary/api.py
├── validation/validation.py
├── application/application.py
├── core/models.py
├── adapters/ai_adapter.py, database_adapter.py, hosting_adapter.py, runtime_support.py, scheduler_adapter.py, social_adapter.py
└── README.md
```

## lead_finder_7

```text
lead_finder_7/
├── boundary/api.py
├── validation/validation.py
├── application/application.py
├── core/models.py
├── adapters/ai_adapter.py, database_adapter.py, hosting_adapter.py, runtime_support.py, source_adapter.py
└── README.md
```

## secure_login_5

```text
secure_login_5/
├── boundary/api.py
├── validation/validation.py
├── application/application.py
├── core/models.py
├── adapters/database_adapter.py, hosting_adapter.py, runtime_support.py, security_adapter.py
└── README.md
```
