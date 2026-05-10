"""Application/orchestration layer for organizer.

The CLI boundary sends validated requests here. This layer coordinates
the concrete organize/analyze/backup use-cases without owning low-level I/O.
"""

from pathlib import Path

try:
    from .backup_service import create_backup, get_backups, restore_backup
    from .models import BackupCommandInput, OrganizeFilesInput
    from .organize_service import analyze_directory, organize_files
except ImportError:
    from backup_service import create_backup, get_backups, restore_backup
    from models import BackupCommandInput, OrganizeFilesInput
    from organize_service import analyze_directory, organize_files


# ============================================
# Application / Orchestration - Public use cases
# Start reading internals from here.
# ============================================
def run_organize(input_data: OrganizeFilesInput):
    """
    Run the main organize use-case with an already-validated organize input model.

    Flow:
        organize -> run_organize
        run_organize
            -> organize_files
    """
    # The CLI prepares the input model; the application delegates to the use-case.
    return organize_files(input_data)


def run_analyze(source_dir: Path, max_files: int):
    """
    Run the read-only analysis use-case without mutating the source directory.

    Flow:
        analyze -> run_analyze
        run_analyze
            -> analyze_directory
    """
    # Analysis is read-only: inspect first, mutate nothing.
    return analyze_directory(source_dir, max_files)


def run_backup(input_data: BackupCommandInput):
    """
    Run the backup use-case with an already-validated backup input model.

    Flow:
        backup -> run_backup
        run_backup
            -> create_backup
    """
    # Backup is a separate use-case so destructive operations can opt into it explicitly.
    return create_backup(input_data)


def list_backups(backup_dir: Path) -> list[Path]:
    """
    Return raw backup paths for the CLI to format and present.

    Flow:
        backup --list -> list_backups
        list_backups
            -> get_backups
    """
    # Return raw paths here; formatting belongs in the CLI boundary.
    return get_backups(backup_dir)


def run_restore(backup_path: Path, restore_dir: Path, backup_dir: Path) -> bool:
    """
    Restore one backup archive into the requested destination directory.

    Flow:
        backup --restore -> run_restore
        run_restore
            -> restore_backup
    """
    return restore_backup(backup_path, restore_dir, backup_dir)
