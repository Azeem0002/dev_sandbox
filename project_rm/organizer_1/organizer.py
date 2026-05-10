#!/usr/bin/env python3
"""CLI boundary for organizer.

This file gathers user input, confirms risky actions, and formats output.
The real use-cases live below the boundary in the application/service layers.
"""

import sys
from datetime import datetime
from pathlib import Path

import typer

try:
    from .application import list_backups, run_analyze, run_backup, run_organize, run_restore
    from .models import BACKUP_DIR, MAX_FILES, BackupCommandInput, ConflictStrategy, OrganizeFilesInput, Validated, ValidationError
    from .runtime_support import setup_logger, setup_runtime_environment
    from .validation import parse_conflict_strategy
except ImportError:
    from application import list_backups, run_analyze, run_backup, run_organize, run_restore
    from models import BACKUP_DIR, MAX_FILES, BackupCommandInput, ConflictStrategy, OrganizeFilesInput, Validated, ValidationError
    from runtime_support import setup_logger, setup_runtime_environment
    from validation import parse_conflict_strategy


app = typer.Typer(
    help="Production File Organizer with Backup System",
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)


# ============================================
# CLI - Thin wrapper around orchestration
# ============================================
@app.callback()
def init() -> None:
    """Initialize the runtime environment for this module."""
    log_file = setup_runtime_environment()
    setup_logger(log_file)


def _get_validated_value[T](validation: Validated[T], context: str = "") -> T:
    """Bridge structured validation results into CLI output + exit behavior."""
    if validation.is_invalid:
        typer.echo(f"{context or 'Validation'} failed:")
        for error in validation.errors:
            typer.echo(f"  - {error}")
        raise typer.Exit(1)

    value = validation.value
    if value is None:
        raise ValidationError(f"{context or 'Value'} unexpectedly None after validation")
    return value


def _prompt_for_conflict_strategy() -> ConflictStrategy:
    """Interactive boundary helper for choosing how duplicate files should be handled."""
    typer.echo("\nConflict Resolution Strategy")
    typer.echo("1. Skip duplicates")
    typer.echo("2. Rename duplicates")
    typer.echo("3. Overwrite duplicates")
    typer.echo("4. Delete conflicted source files")
    typer.echo("5. Cancel")

    while True:
        choice = typer.prompt("Choose strategy (1-5)", default="1", show_choices=False).strip()
        if choice == "1":
            return ConflictStrategy.SKIP
        if choice == "2":
            return ConflictStrategy.RENAME
        if choice == "3":
            if typer.confirm("Overwrite will delete target duplicate files. Continue?"):
                return ConflictStrategy.OVERWRITE
            continue
        if choice == "4":
            if typer.confirm("Delete will remove conflicted source files. Continue?"):
                return ConflictStrategy.DELETE
            continue
        if choice == "5":
            raise typer.Abort("Operation cancelled by user.")
        typer.echo("Invalid choice. Please enter 1-5.")


def _resolve_conflict_strategy(strategy: str, interactive: bool) -> ConflictStrategy:
    # Interactive mode asks the user directly.
    # Non-interactive mode parses the CLI option value.
    """Resolve conflict strategy."""
    if interactive:
        return _prompt_for_conflict_strategy()
    return _get_validated_value(parse_conflict_strategy(strategy), "Conflict strategy")


def _confirm_destructive_organize_strategy(
    conflict_strategy: ConflictStrategy,
    dry_run: bool,
    backup_enabled: bool,
) -> bool:
    """Ask for extra confirmation before destructive organize modes run."""
    if dry_run:
        return backup_enabled

    if conflict_strategy == ConflictStrategy.DELETE:
        typer.echo("\nDELETE STRATEGY SELECTED")
        typer.echo("Conflicted source files will be permanently deleted.")
        if not typer.confirm("Are you sure you want to delete files?"):
            raise typer.Abort("Delete strategy cancelled by user.")
        if not backup_enabled and typer.confirm("Create backup before proceeding?"):
            return True
        return backup_enabled

    if conflict_strategy == ConflictStrategy.OVERWRITE:
        typer.echo("\nOVERWRITE STRATEGY SELECTED")
        typer.echo("Duplicate target files will be overwritten.")
        if not typer.confirm("Are you absolutely sure you want to continue?"):
            raise typer.Abort("Overwrite strategy cancelled by user.")
        if not backup_enabled and typer.confirm("Create backup before proceeding?"):
            return True

    return backup_enabled


def _confirm_organize_execution(input_data: OrganizeFilesInput) -> None:
    """Final boundary confirmation before real filesystem mutations begin."""
    if input_data.dry_run:
        return

    typer.echo("\nExecution Summary")
    typer.echo(f"Source: {input_data.source_dir}")
    typer.echo(f"Strategy: {input_data.conflict_strategy.value}")
    typer.echo(f"Mode: {'Recursive' if input_data.recursive else 'Current folder only'}")
    typer.echo(f"Max files: {input_data.max_files}")
    typer.echo(f"Backup: {'Yes' if input_data.backup else 'No'}")

    if not typer.confirm("Proceed with file organization?"):
        raise typer.Abort("Operation cancelled by user.")


@app.command()
def organize(
    source_dir: Path = typer.Argument(..., help="Directory to organize"),
    dry_run: bool = typer.Option(True, help="Preview changes (default) / Execute organization"),
    strategy: str = typer.Option("skip", "--strategy", "-s", help="skip|rename|overwrite|delete"),
    interactive: bool = typer.Option(False, "--interactive", "-i", help="Choose strategy interactively"),
    recursive: bool = typer.Option(False, "--recursive", "-r", help="Process subdirectories"),
    max_files: int = typer.Option(MAX_FILES, "--max-files", help="Maximum files to process"),
    backup: bool = typer.Option(False, "--backup", "-b", help="Create backup before organizing"),
) -> None:
    """Organize."""
    try:
        conflict_strategy = _resolve_conflict_strategy(strategy, interactive)
        backup = _confirm_destructive_organize_strategy(conflict_strategy, dry_run, backup)
        organize_input = OrganizeFilesInput(
            source_dir=source_dir,
            dry_run=dry_run,
            conflict_strategy=conflict_strategy,
            recursive=recursive,
            max_files=max_files,
            backup=backup,
        )

        backup_path: Path | None = None
        if organize_input.backup and not organize_input.dry_run:
            typer.echo("\nCreating backup...")
            backup_path = run_backup(
                BackupCommandInput(
                    source_dir=organize_input.source_dir,
                    backup_dir=BACKUP_DIR,
                    compress=True,
                    compression_format="zip",
                )
            )
            if backup_path:
                typer.echo(f"Backup created: {backup_path}")
            elif not typer.confirm("Backup creation failed. Continue without backup?"):
                raise typer.Exit(1)

        _confirm_organize_execution(organize_input)
        result = run_organize(organize_input)

        if organize_input.dry_run:
            typer.echo("\nDRY RUN MODE")
            typer.echo("No files were modified.")
        else:
            typer.echo("\nExecuting file organization")

        typer.echo("\nResults:")
        typer.echo(f"  Organized: {result.organized}")
        typer.echo(f"  Skipped: {result.skipped}")
        typer.echo(f"  Conflicts: {result.conflicts}")
        typer.echo(f"  Errors: {result.errors}")
        if result.discovered_categories:
            typer.echo(f"  Categories: {', '.join(sorted(result.discovered_categories))}")
        if backup_path:
            typer.echo(f"  Backup: {backup_path}")
    except ValidationError as error:
        typer.echo(f"Validation Error: {error}")
        raise typer.Exit(1)
    except typer.Abort as error:
        typer.echo(f"Operation cancelled: {error}")
        raise typer.Exit(0)
    except Exception as error:
        typer.echo(f"Error: {error}")
        raise typer.Exit(1)


@app.command()
def backup(
    source_dir: Path = typer.Argument(..., help="Directory to backup"),
    backup_dir: Path = typer.Option(BACKUP_DIR, "--backup-dir", "-d", help="Directory to store backups"),
    compress: bool = typer.Option(True, "--compress/--no-compress", help="Compress backup"),
    compression_format: str = typer.Option("zip", "--format", "-f", help="zip or tar.gz"),
    list_backups: bool = typer.Option(False, "--list", "-l", help="List existing backups"),
    restore: Path | None = typer.Option(None, "--restore", "-r", help="Restore a specific backup"),
    restore_to: Path = typer.Option(Path.cwd(), "--restore-to", "-t", help="Directory to restore to"),
) -> None:
    """Backup."""
    try:
        if list_backups:
            backups = list_backups(backup_dir)
            if not backups:
                typer.echo("No backups found.")
                return
            typer.echo(f"\nAvailable backups in {backup_dir}:")
            for backup_path in backups:
                size = backup_path.stat().st_size
                modified = datetime.fromtimestamp(backup_path.stat().st_mtime)
                size_str = f"{size/1024/1024:.1f} MB" if size < 1024**3 else f"{size/1024**3:.2f} GB"
                typer.echo(f"  - {backup_path.name} ({size_str}, {modified:%Y-%m-%d %H:%M})")
            return

        if restore:
            if not restore.exists():
                typer.echo(f"Backup not found: {restore}")
                raise typer.Exit(1)
            if not typer.confirm(f"Restore {restore.name} to {restore_to}?"):
                raise typer.Abort("Restore cancelled by user.")
            if run_restore(restore, restore_to, backup_dir):
                typer.echo(f"Backup restored successfully to {restore_to}")
                return
            typer.echo("Backup restore failed")
            raise typer.Exit(1)

        if not typer.confirm(f"Create backup of {source_dir} to {backup_dir}?"):
            raise typer.Abort("Backup cancelled by user.")

        backup_path = run_backup(
            BackupCommandInput(
                source_dir=source_dir,
                backup_dir=backup_dir,
                compress=compress,
                compression_format=compression_format,
            )
        )
        if backup_path:
            size = backup_path.stat().st_size
            size_str = f"{size/1024/1024:.1f} MB" if size < 1024**3 else f"{size/1024**3:.2f} GB"
            typer.echo(f"Backup created successfully: {backup_path} ({size_str})")
            return
        typer.echo("Backup creation failed")
        raise typer.Exit(1)
    except ValidationError as error:
        typer.echo(f"Validation Error: {error}")
        raise typer.Exit(1)
    except typer.Abort as error:
        typer.echo(f"Operation cancelled: {error}")
        raise typer.Exit(0)
    except Exception as error:
        typer.echo(f"Error: {error}")
        raise typer.Exit(1)


@app.command()
def analyze(
    source_dir: Path = typer.Argument(..., help="Directory to analyze"),
    max_files: int = typer.Option(50000, help="Maximum files to scan"),
) -> None:
    """Analyze."""
    try:
        analysis = run_analyze(source_dir, max_files)
        typer.echo(f"\nAnalysis of: {analysis.source_dir}")
        typer.echo(f"  Total files: {analysis.file_count:,}")
        typer.echo(f"  Unique categories: {len(analysis.categories)}")
        if analysis.categories:
            typer.echo("\n  Categories that would be created:")
            for category in analysis.categories:
                count = analysis.category_counts.get(category, 0)
                percentage = (count / analysis.file_count * 100) if analysis.file_count > 0 else 0
                typer.echo(f"    - {category}/ ({count:,} files, {percentage:.1f}%)")
    except Exception as error:
        typer.echo(f"Error: {error}")
        raise typer.Exit(1)


def main() -> None:
    """Run the module entrypoint."""
    app()


if __name__ == "__main__":
    main()
