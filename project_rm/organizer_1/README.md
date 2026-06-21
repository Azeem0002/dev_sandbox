# Organizer

## Purpose
File organizer with backup, restore, validation, and crash-resume support.

## Boundary
- CLI entrypoint: `organizer.py`
- Main commands: `organize`, `backup`, `analyze`

## Layer Map
- Boundary: `organizer.py`
- Core models: `models.py`
- Validation/parsing: `validation.py`
- Reusable file helpers: `file_utils.py`
- Runtime/logging: `runtime_adapter.py`
- Application workflows: `organize_service.py`, `backup_service.py`

## Reusable Patterns
- Railway-style validation container
- Secure filesystem validation
- Category extraction from extensions
- Safe copy with verification and retries
- Resume-state persistence for long-running operations

## Flow
Input -> Validate -> Analyze/Backup/Organize -> Log -> Present

## High-Risk Areas
- Path traversal
- Symlink abuse
- Disk exhaustion
- Partial copy corruption
- Destructive conflict strategies

## Rules of Thumb
- Learn the reusable validators first
- Treat CLI prompts as boundary-only code
- Keep file movement logic out of the CLI
- Persist progress only for real long-running operations

## Study Order
1. `models.py`
2. `validation.py`
3. `file_utils.py`
4. `organize_service.py`
5. `backup_service.py`
6. `organizer.py`

## Developer Contact

For reviews, custom automation, or partnership discussions, show the developer contact in the product/docs through configurable values:

```text
Email: DEV_CONTACT_EMAIL
WhatsApp: DEV_CONTACT_WHATSAPP
```
