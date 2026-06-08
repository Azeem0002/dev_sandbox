# Project Commands

Run these commands from the repo root:

```bash
cd /home/az/dev_sandbox/project_rm
```

## Scheduler

CLI entrypoint:

```bash
python3 scheduler_3/scheduler.py --help
```

Common commands:

```bash
python3 scheduler_3/scheduler.py add --interactive
python3 scheduler_3/scheduler.py add --name "Daily list" --command "ls" --type weekly --days 1,2,3,4,5 --time 09:00
python3 scheduler_3/scheduler.py add --name "One-time check" --command "python3 --version" --type once --time "2026-06-07T09:00:00+01:00"
python3 scheduler_3/scheduler.py list
python3 scheduler_3/scheduler.py list --verbose
python3 scheduler_3/scheduler.py start
python3 scheduler_3/scheduler.py start --foreground
python3 scheduler_3/scheduler.py status
python3 scheduler_3/scheduler.py pause JOB_ID_OR_NAME
python3 scheduler_3/scheduler.py resume JOB_ID_OR_NAME
python3 scheduler_3/scheduler.py remove JOB_ID_OR_NAME
python3 scheduler_3/scheduler.py remove JOB_ID_OR_NAME --force
python3 scheduler_3/scheduler.py stop
python3 scheduler_3/scheduler.py install
python3 scheduler_3/scheduler.py install --system
```

Command validation note:

```bash
python3 scheduler_3/scheduler.py add --name "Bad" --command "proj" --type weekly --days 1 --time 09:00
```

The scheduler checks the first command word with `shutil.which(...)`.
Installed executables like `ls`, `python`, or `python3` resolve through `PATH`; unknown names like `proj` fail.

## Autoclear

Controller entrypoint:

```bash
python3 autoclear_2/controller.py --help
```

Common commands:

```bash
python3 autoclear_2/controller.py status
python3 autoclear_2/controller.py start --interval 10s
python3 autoclear_2/controller.py start --interval 5m
python3 autoclear_2/controller.py restart --interval 1h
python3 autoclear_2/controller.py stop
python3 autoclear_2/controller.py install-service --interval 1h
python3 autoclear_2/controller.py install-service --interval 1h --system
```

Worker entrypoint:

```bash
python3 autoclear_2/autoclear.py --once
python3 autoclear_2/autoclear.py 3600
```

## Organizer

CLI entrypoint:

```bash
python3 organizer_1/organizer.py --help
```

Common commands:

```bash
python3 organizer_1/organizer.py analyze /path/to/folder
python3 organizer_1/organizer.py organize /path/to/folder
python3 organizer_1/organizer.py organize /path/to/folder --interactive
python3 organizer_1/organizer.py organize /path/to/folder --recursive
python3 organizer_1/organizer.py organize /path/to/folder --no-dry-run --backup
python3 organizer_1/organizer.py organize /path/to/folder --strategy rename
python3 organizer_1/organizer.py backup /path/to/folder
python3 organizer_1/organizer.py backup /path/to/folder --no-compress
python3 organizer_1/organizer.py backup /path/to/folder --format zip
python3 organizer_1/organizer.py backup /path/to/folder --backup-dir /path/to/backups
python3 organizer_1/organizer.py backup /path/to/folder --list
python3 organizer_1/organizer.py backup /path/to/folder --restore /path/to/backup.zip --restore-to /path/to/restore
```

## Scraper 4

CLI entrypoint:

```bash
cd scraper_4
uv run scraper --help
```

Common commands:

```bash
uv run scraper research --interactive
uv run scraper trends --mode products --keyword laptop --region US --export csv
uv run scraper trends --mode jobs --keyword python --region NG --export json
uv run scraper scrape "https://example.com" --mode products --export csv
uv run scraper scrape "https://example.com" --browser --selector "a" --mode products
uv run scraper history
```

Install shortcut for use from anywhere:

```bash
uv tool install /home/az/dev_sandbox/project_rm/scraper_4
scraper --help
```

Optional API boundary:

```bash
cd scraper_4
uv run uvicorn api:app --reload
```
