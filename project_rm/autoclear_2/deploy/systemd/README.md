# Autoclear systemd units

These are user-level `systemd` templates for Linux.

They run `autoclear.py` in `--once` mode through `autoclear.timer`.
That is the correct `systemd` shape here: `systemd` handles scheduling, Python handles the clear operation.

## Files

- `autoclear.service`: one-shot worker unit
- `autoclear.timer`: recurring schedule

## Before install

Replace these placeholders in `autoclear.service`:

- `@PROJECT_ROOT@` -> absolute path to this repo
- `@PYTHON_BIN@` -> absolute path to the Python interpreter you want to run

Example values:

- `@PROJECT_ROOT@` -> `/home/az/dev_sandbox/project_rm`
- `@PYTHON_BIN@` -> `/usr/bin/python3`

## Install for current user

```bash
mkdir -p ~/.config/systemd/user
cp autoclear.service autoclear.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now autoclear.timer
systemctl --user status autoclear.timer
```

## Change frequency

Edit `autoclear.timer` and change:

```ini
OnUnitActiveSec=1h
```

Examples:

- `OnUnitActiveSec=30s`
- `OnUnitActiveSec=15m`
- `OnUnitActiveSec=2h`

After editing:

```bash
systemctl --user daemon-reload
systemctl --user restart autoclear.timer
```

## Stop or disable

```bash
systemctl --user stop autoclear.timer
systemctl --user disable autoclear.timer
systemctl --user stop autoclear.service
```

## Logs

```bash
journalctl --user -u autoclear.service -f
```
