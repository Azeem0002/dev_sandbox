"""Validation and parsing layer for organizer.

These functions turn raw paths/options into trusted domain inputs and collect
structured validation errors instead of crashing early.
"""

import os
import time
from functools import partial
from pathlib import Path

try:
    from .models import ConflictStrategy, Validated, ValidationError
except ImportError:
    from models import ConflictStrategy, Validated, ValidationError


# REUSABLE: existence validation is generic and portable across projects.
def validate_path_exists(path: Path) -> Validated[Path]:
    # Return a structured validation result instead of raising immediately.
    # That lets higher layers accumulate/report multiple errors cleanly.
    """Validate path exists."""
    if not path.exists():
        return Validated(None, [ValidationError(f"Path does not exist: {path}")])
    return Validated(path)


# REUSABLE: directory type validation is generic and portable across projects.
def validate_is_directory(path: Path) -> Validated[Path]:
    """Validate is directory."""
    if not path.is_dir():
        return Validated(None, [ValidationError(f"Path is not a directory: {path}")])
    return Validated(path)


# REUSABLE: readable permission validation is generic and portable across projects.
def validate_is_readable(path: Path) -> Validated[Path]:
    """Validate is readable."""
    try:
        # `next(iterdir(), None)` is a cheap permission probe:
        # if listing the directory fails, we likely lack read access.
        next(path.iterdir(), None)
        return Validated(path)
    except PermissionError:
        return Validated(None, [ValidationError(f"No read permission for directory: {path}")])


# REUSABLE: file type validation is generic and portable across projects.
def validate_is_file(path: Path) -> Validated[Path]:
    """Validate is file."""
    if not path.is_file():
        return Validated(None, [ValidationError(f"Path is not a file: {path}")])
    return Validated(path)


# REUSABLE: bounded scan validation is a useful safety pattern for CLI tools.
def validate_file_count_within_limit(directory: Path, max_files: int) -> Validated[Path]:
    """Validate file count within limit."""
    try:
        count = 0
        for item in directory.iterdir():
            if item.is_file():
                count += 1
                if count > max_files:
                    return Validated(None, [ValidationError(f"Exceeds {max_files} files")])
        return Validated(directory)
    except OSError as error:
        return Validated(None, [ValidationError(f"Cannot access directory: {error}")])


# REUSABLE: base-directory containment check is a strong path traversal defense.
def validate_within_base(path: Path, base_dir: Path) -> Validated[Path]:
    """Validate within base."""
    try:
        resolved = path.resolve()  # collapse "..", symlinks, and relative parts into a real absolute path
        if not resolved.is_relative_to(base_dir):
            return Validated(None, [ValidationError(f"Path outside allowed area: {path}")])
        return Validated(resolved)
    except (OSError, RuntimeError) as error:
        return Validated(None, [ValidationError(f"Invalid path: {error}")])


# REUSABLE: symlink defense is a solid reusable file-system security primitive.
def validate_not_symlinks(path: Path) -> Validated[Path]:
    """Validate not symlinks."""
    current = path
    while current != current.parent:
        # Walk upward one path component at a time and reject any symlink hop.
        if current.is_symlink():
            return Validated(None, [ValidationError(f"Symlink in path: {current}")])
        current = current.parent
    return Validated(path)


# REUSABLE: write-probe validation is a reusable TOCTOU-resistant pattern.
def validate_is_writable_secure(path: Path) -> Validated[Path]:
    """Validate is writable secure."""
    if path.exists():
        if not path.is_dir():
            return Validated(None, [ValidationError(f"Not a directory: {path}")])

        # Randomized temp file name reduces collision risk between concurrent processes.
        test_name = f".write_test_{os.getpid()}_{int(time.time())}_{os.urandom(4).hex()}"
        test_file = path / test_name
        try:
            test_file.touch(exist_ok=False)
            test_file.unlink(missing_ok=True)
            return Validated(path)
        except FileExistsError:
            return Validated(None, [ValidationError(f"Test file collision (retry): {path}")])
        except PermissionError:
            return Validated(None, [ValidationError(f"No write permission: {path}")])

    parent = path.parent
    if not parent.exists():
        return Validated(None, [ValidationError(f"Parent doesn't exist: {parent}")])
    return validate_is_writable_secure(parent)


def parse_source_directory_secure(path: Path, max_files: int = 10000) -> Validated[Path]:
    # Bind-chain mental model:
    # each step only runs if the previous validation succeeded.
    """Parse source directory secure."""
    check_file_limit = partial(validate_file_count_within_limit, max_files=max_files)
    return (
        validate_within_base(path, Path.home())
        .bind(validate_path_exists)
        .bind(validate_is_directory)
        .bind(validate_is_readable)
        .bind(check_file_limit)
    )


def parse_backup_source(path: Path) -> Validated[Path]:
    """Parse backup source."""
    return validate_path_exists(path).bind(validate_is_directory).bind(validate_is_readable)


def parse_backup_destination(path: Path) -> Validated[Path]:
    """Parse backup destination."""
    def parse_directory_or_creatable(candidate: Path) -> Validated[Path]:
        """Parse directory or creatable."""
        if candidate.exists():
            return validate_is_directory(candidate)

        parent_validation = validate_path_exists(candidate.parent).bind(validate_is_writable_secure)
        if parent_validation.is_valid:
            return Validated(candidate)
        return Validated(None, [ValidationError(f"Cannot create directory: {candidate}")])

    return (
        validate_within_base(path, Path.home())
        .bind(parse_directory_or_creatable)
        .bind(validate_not_symlinks)
        .bind(validate_is_writable_secure)
    )


# REUSABLE: enum parsing with sanitation is a generic CLI/config pattern.
def parse_conflict_strategy(value: str) -> Validated[ConflictStrategy]:
    """Parse conflict strategy."""
    try:
        clean_value = value.strip().lower()
        if not clean_value.isalnum():
            return Validated(None, [ValidationError("Invalid characters in strategy")])

        return Validated(ConflictStrategy(clean_value))
    except ValueError:
        valid_options = ", ".join(strategy.value for strategy in ConflictStrategy)
        return Validated(None, [ValidationError(f"Invalid strategy '{value}'. Choose from: {valid_options}")])
    except (AttributeError, TypeError):
        return Validated(None, [ValidationError("Invalid input")])
