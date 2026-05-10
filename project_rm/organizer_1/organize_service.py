"""Organization use-cases for organizer.

This module owns analysis, move decisions, conflict handling, and resume-state
checkpointing for long-running organize operations.
"""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterator

from loguru import logger
from tqdm import tqdm

try:
    from .file_utils import extract_file_category, gather_file_metadata, generate_unique_filename
    from .models import (
        DirectoryAnalysis,
        ConflictStrategy,
        OrganizeFilesInput,
        OrganizeOperationState,
        OrganizationResult,
        ORGANIZE_STATE_PATH,
        STATE_DIR,
        ValidationError,
    )
    from .validation import parse_source_directory_secure
except ImportError:
    from file_utils import extract_file_category, gather_file_metadata, generate_unique_filename
    from models import (
        DirectoryAnalysis,
        ConflictStrategy,
        OrganizeFilesInput,
        OrganizeOperationState,
        OrganizationResult,
        ORGANIZE_STATE_PATH,
        STATE_DIR,
        ValidationError,
    )
    from validation import parse_source_directory_secure


def validate_source_directory_or_raise(source_dir: Path, max_files: int) -> Path:
    """
    Flow:
        analyze | organize -> validate_source_directory_or_raise
        validate_source_directory_or_raise
            -> parse_source_directory_secure
    """
    validation = parse_source_directory_secure(source_dir, max_files)
    if validation.is_invalid:
        errors = "\n".join(str(error) for error in validation.errors)
        raise ValidationError(f"Invalid source directory:\n{errors}")

    value = validation.value
    if value is None:
        raise ValidationError("Source directory unexpectedly None after validation")
    return value


def _save_organize_state(state: OrganizeOperationState) -> None:
    """Persist crash-recovery state so a long organize run can resume safely."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_dir": state.source_dir,
        "conflict_strategy": state.conflict_strategy,
        "recursive": state.recursive,
        "max_files": state.max_files,
        "started_at": state.started_at,
        "completed_paths": state.completed_paths,
    }
    temp_path = ORGANIZE_STATE_PATH.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(ORGANIZE_STATE_PATH)


def _load_organize_state() -> OrganizeOperationState | None:
    """Load the previous organize checkpoint, if one exists."""
    if not ORGANIZE_STATE_PATH.exists():
        return None

    data = json.loads(ORGANIZE_STATE_PATH.read_text(encoding="utf-8"))
    return OrganizeOperationState(
        source_dir=str(data["source_dir"]),
        conflict_strategy=str(data["conflict_strategy"]),
        recursive=bool(data["recursive"]),
        max_files=int(data["max_files"]),
        started_at=str(data["started_at"]),
        completed_paths=[str(path) for path in data.get("completed_paths", [])],
    )


def _clear_organize_state() -> None:
    """Delete recovery state after a clean completion."""
    ORGANIZE_STATE_PATH.unlink(missing_ok=True)


def _get_file_iterator(source_dir: Path, recursive: bool) -> Iterator[Path]:
    """Return file iterator."""
    if recursive:
        return (item for item in source_dir.rglob("*") if item.is_file())
    return (item for item in source_dir.iterdir() if item.is_file())


def _collect_files_for_organization(source_dir: Path, recursive: bool, max_files: int) -> list[Path]:
    """Collect files for organization."""
    return list(_get_file_iterator(source_dir, recursive))[:max_files]


def _resolve_target_path(target_path: Path, strategy: ConflictStrategy) -> Path | None:
    """Resolve target path."""
    if strategy is ConflictStrategy.SKIP:
        return None
    if strategy is ConflictStrategy.RENAME:
        return generate_unique_filename(target_path)
    if strategy is ConflictStrategy.OVERWRITE:
        target_path.unlink(missing_ok=True)
        return target_path
    return target_path


def _prepare_resume_state(
    validated_source: Path,
    input_data: OrganizeFilesInput,
) -> tuple[OrganizeOperationState | None, set[str]]:
    """Decide whether to start fresh, resume, or reject a mismatched resume state."""
    if input_data.dry_run:
        return None, set()

    current_source = str(validated_source.resolve())
    existing_state = _load_organize_state()
    if existing_state is None:
        state = OrganizeOperationState(
            source_dir=current_source,
            conflict_strategy=input_data.conflict_strategy.value,
            recursive=input_data.recursive,
            max_files=input_data.max_files,
            started_at=datetime.now().isoformat(),
        )
        _save_organize_state(state)
        return state, set()

    if (
        existing_state.source_dir != current_source
        or existing_state.conflict_strategy != input_data.conflict_strategy.value
        or existing_state.recursive != input_data.recursive
        or existing_state.max_files != input_data.max_files
    ):
        raise ValidationError(
            "Existing crash-recovery state does not match this organize run. "
            "Clear or resume the previous run first."
        )

    logger.info(
        f"Resuming previous organize run from {existing_state.started_at}. "
        f"Already processed: {len(existing_state.completed_paths)} files."
    )
    return existing_state, set(existing_state.completed_paths)


def _mark_file_completed(
    state: OrganizeOperationState | None,
    completed_paths: set[str],
    relative_path: str,
) -> None:
    """Checkpoint one completed relative path so resume can skip it later."""
    if state is None or relative_path in completed_paths:
        return
    completed_paths.add(relative_path)
    state.completed_paths.append(relative_path)
    _save_organize_state(state)


def _log_organize_results(result: OrganizationResult, dry_run: bool) -> None:
    """Log organize results."""
    mode = "DRY RUN" if dry_run else "COMPLETE"
    logger.success(
        f"{mode}: {result.organized} organized, "
        f"{result.skipped} skipped, "
        f"{result.conflicts} conflicts, "
        f"{result.errors} errors"
    )
    if result.discovered_categories:
        logger.info(f"Categories: {', '.join(sorted(result.discovered_categories))}")


def _organize_single_file(
    file_path: Path,
    source_dir: Path,
    strategy: ConflictStrategy,
    created_categories: set[str],
    result: OrganizationResult,
    dry_run: bool,
) -> None:
    """Apply one move/delete decision according to the chosen conflict policy."""
    file_info = gather_file_metadata(file_path)
    result.discovered_categories.add(file_info.category)

    category_dir = source_dir / file_info.category
    if file_info.category not in created_categories and not category_dir.exists():
        if not dry_run:
            category_dir.mkdir(exist_ok=True)
        created_categories.add(file_info.category)
        result.created_categories_count += 1

    if file_path.parent == category_dir:
        result.skipped += 1
        return

    target_path = category_dir / file_info.name
    if target_path.exists():
        if strategy is ConflictStrategy.DELETE:
            if not dry_run:
                file_path.unlink(missing_ok=True)
            result.organized += 1
            return

        resolved_target = _resolve_target_path(target_path, strategy)
        if resolved_target is None:
            result.conflicts += 1
            return
        target_path = resolved_target

    if not dry_run:
        shutil.move(str(file_path), str(target_path))
        result.operations.append((file_path, target_path))

    result.organized += 1


def analyze_directory(source_dir: Path, max_files: int) -> DirectoryAnalysis:
    """
    Flow:
        analyze -> analyze_directory
        analyze_directory
            -> validate_source_directory_or_raise
            -> extract_file_category
    """
    validated_source = validate_source_directory_or_raise(source_dir, max_files)
    category_counts: dict[str, int] = {}
    file_count = 0

    for item in validated_source.iterdir():
        if item.is_file():
            file_count += 1
            try:
                category = extract_file_category(item)
            except ValidationError:
                continue
            category_counts[category] = category_counts.get(category, 0) + 1

    return DirectoryAnalysis(
        source_dir=validated_source,
        file_count=file_count,
        category_counts=category_counts,
    )


# ============================================
# Application / Orchestration - Public use cases
# Start reading internals from here.
# ============================================
def organize_files(input_data: OrganizeFilesInput) -> OrganizationResult:
    """
    Flow:
        organize -> organize_files
        organize_files
            -> validate_source_directory_or_raise
            -> _prepare_resume_state
            -> _collect_files_for_organization
            -> _organize_single_file
    """
    validated_source = validate_source_directory_or_raise(input_data.source_dir, input_data.max_files)
    state, completed_paths = _prepare_resume_state(validated_source, input_data)
    result = OrganizationResult()
    created_categories: set[str] = set()
    all_files = _collect_files_for_organization(validated_source, input_data.recursive, input_data.max_files)

    if not all_files:
        logger.info("No files to organize")
        _clear_organize_state()
        return result

    pending_files = [
        file_path
        for file_path in all_files
        if input_data.dry_run or str(file_path.relative_to(validated_source)) not in completed_paths
    ]

    logger.info(f"Found {len(all_files)} files to organize")
    if state is not None and completed_paths:
        logger.info(f"Resuming with {len(pending_files)} files remaining")

    try:
        with tqdm(
            total=len(pending_files),
            desc="Organizing",
            unit="files",
            colour="blue",
            bar_format="{l_bar}{bar:40}{r_bar}",
            ncols=80,
            mininterval=0.1,
        ) as progress:
            for file_path in pending_files:
                relative_path = str(file_path.relative_to(validated_source))
                try:
                    _organize_single_file(
                        file_path=file_path,
                        source_dir=validated_source,
                        strategy=input_data.conflict_strategy,
                        created_categories=created_categories,
                        result=result,
                        dry_run=input_data.dry_run,
                    )
                except ValidationError as error:
                    logger.error(f"Validation failed for {file_path.name}: {error}")
                    result.errors += 1
                except (OSError, RuntimeError) as error:
                    logger.error(f"Failed to process {file_path.name}: {error}")
                    result.errors += 1

                _mark_file_completed(state, completed_paths, relative_path)
                progress.update(1)
    except KeyboardInterrupt:
        logger.warning("Organization interrupted. Progress was saved for resume.")
        raise
    except Exception:
        logger.exception("Organization crashed. Progress was saved for resume.")
        raise
    else:
        _clear_organize_state()

    _log_organize_results(result, input_data.dry_run)
    return result
