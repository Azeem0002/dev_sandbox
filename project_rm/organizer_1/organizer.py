#!/usr/bin/env python3
"""
file_organizer.py - Production File Organizer with Backup System
Clean Architecture with Parser Pattern - Complete Version with Disk Space Management

DESIGN PHILOSOPHY:
1. Separation of Concerns: Each component has a single responsibility
2. Railway-Oriented Programming: Validation chains that don't throw exceptions
3. Security-First: All user inputs are validated and sanitized
4. User Experience: Clear progress feedback and error messages
5. Production Ready: Comprehensive logging, retry logic, and error handling

FEATURES:
• File organization by category (images, documents, etc.)
• Secure backup creation with compression
• Disk space management and monitoring
• Conflict resolution strategies
• Dry-run mode for safe testing
• Comprehensive logging and progress tracking
"""

from __future__ import annotations

import sys
import os
import time
import re
import json
import shutil
import zipfile
import tarfile
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Set, Tuple, Callable, Iterator, Optional
from functools import partial, wraps

import typer
from loguru import logger
from platformdirs import PlatformDirs
from tqdm import tqdm

# =============================================================================
# PARSER PATTERN CORE - Railway-Oriented Programming
# =============================================================================

class ValidationError(Exception):
    """
    Custom validation error for business rule violations.
    
    WHY:
    - Gives semantic meaning to validation failures
    - Lets us distinguish validation errors from system errors
    - Can be caught separately for different handling strategies
    """
    pass


@dataclass
class Validated[T]:
    """
    A container that represents either:
    - a valid value of type T
    - or one/more validation errors
    
    DESIGN PATTERN: Railway-Oriented Programming
    - Green track (valid): value is present, no errors
    - Red track (invalid): value is None, errors present
    
    WHY USE THIS PATTERN?
    - Avoids throwing exceptions during parsing/validation
    - Enables chaining validations safely
    - Composable: validations can be combined
    - Transparent: errors are collected, not lost
    """
    
    # ===========================
    # STATE: Data held by the container
    # ===========================
    
    # Holds the successful value if validation passed
    value: T | None = None
    
    # Holds zero or more validation errors
    # field(default_factory=list) ensures each instance gets its own list
    errors: List[ValidationError] = field(default_factory=list)
    
    # ===========================
    # PROPERTIES: State queries (read-only)
    # ===========================
    
    @property
    def is_valid(self) -> bool:
        """
        Returns True if:
        - a value is present
        - AND no errors exist
        
        WHY:
        - Encodes the invariant in ONE place
        - Makes downstream logic simple and readable
        - Single source of truth for validity
        """
        return self.value is not None and not self.errors
    
    @property
    def is_invalid(self) -> bool:
        """Logical opposite of is_valid."""
        return not self.is_valid
    
    # ===========================
    # BOUNDARY OPERATIONS: Exit the railway
    # ===========================
    
    def get_or_raise(self) -> T:
        """
        Boundary method: EXIT the validation railway.
        - INSIDE the system: no exceptions
        - AT THE EDGE: raise if invalid
        
        WHY:
        - Clean separation of concerns
        - Domain logic stays exception-free
        - Converts validation results to exceptions at boundaries
        """
        if self.is_invalid:
            # Raise the first validation error if present
            # (User mistake: error message to output)
            error_msg = str(self.errors[0]) if self.errors else "Invalid value"
            raise ValidationError(error_msg)
        
        # ASSERTION: Enforce the invariant
        assert self.value is not None, "Invariant broken: value must exist when valid"
        return self.value
    
    # ===========================
    # TRANSFORMATIONS: Inside the railway
    # ===========================
    
    def map[U](self, op: Callable[[T], U]) -> Validated[U]:
        """
        Functor map: Transform value INSIDE the container safely.
        - Transforms the value ONLY if valid
        - Errors are preserved unchanged
        - Returns a new Validated container
        
        WHY:
        - Allows safe transformations without branching logic
        - Keeps error state intact
        - Functional programming style
        """
        if self.is_invalid:
            # No transformation if already invalid
            return Validated(None, self.errors.copy())
        
        # ASSERTION: Enforce invariant before using value
        assert self.value is not None, "Invariant broken: value must exist when valid"
        
        # Apply transformation and return new Validated container
        new_value = op(self.value)
        return Validated(new_value, self.errors.copy())
    
    def bind[U](self, op: Callable[[T], Validated[U]]) -> Validated[U]:
        """
        Monad bind (flatMap): Chain validation steps.
        - Chains another validation-producing function safely
        - Flattens Validated[Validated[U]] → Validated[U]
        - Combines errors from all steps
        
        WHY:
        - Enables sequential validations
        - Avoids nested containers
        - Collects all errors, not just the first
        """
        if self.is_invalid:
            # Stop the chain if already invalid
            return Validated(None, self.errors.copy())
        
        # ASSERTION: Enforce invariant
        assert self.value is not None, "Invariant broken: value must exist when valid"
        
        # Run the next validation step
        result = op(self.value)
        
        # Combine errors from both steps
        return Validated(result.value, self.errors + result.errors.copy())
    
    # ===========================
    # COMBINATIONS: Parallel validation
    # ===========================
    
    def __and__[U](self, other: Validated[U]) -> Validated[Tuple[T, U]]:
        """
        Applicative combination: Combine independent validations in parallel.
        - Combines TWO independent validations
        - Accumulates errors from both
        - Returns tuple of values if both valid
        
        WHY:
        - Useful when validations do NOT depend on each other
        - Enables parallel-style validation logic
        - User sees all errors at once (full validation feedback)
        """
        if self.is_valid and other.is_valid:
            # ASSERTIONS: Both values must exist
            assert self.value is not None
            assert other.value is not None
            
            # Combine both values into a tuple
            return Validated(
                (self.value, other.value),
                self.errors + other.errors.copy(),
            )
        
        # If either side failed, return all collected errors
        return Validated(None, self.errors + other.errors.copy())

# =============================================================================
# PURE VALIDATORS - Atomic validation functions
# =============================================================================

def validate_path_exists(path: Path) -> Validated[Path]:
    """Validate that a path exists in the filesystem."""
    if not path.exists():
        return Validated(None, [ValidationError(f"Path does not exist: {path}")])
    return Validated(path)


def validate_is_directory(path: Path) -> Validated[Path]:
    """Validate that a path is a directory (not a file)."""
    if not path.is_dir():
        return Validated(None, [ValidationError(f"Path is not a directory: {path}")])
    return Validated(path)


def validate_is_readable(path: Path) -> Validated[Path]:
    """Validate that a directory is readable."""
    try:
        # Try to list directory contents
        next(path.iterdir(), None)
        return Validated(path)
    except PermissionError:
        return Validated(None, [ValidationError(f"No read permission for directory: {path}")])


def validate_is_file(path: Path) -> Validated[Path]:
    """Validate that a path is a file (not a directory)."""
    if not path.is_file():
        return Validated(None, [ValidationError(f"Path is not a file: {path}")])
    return Validated(path)


def validate_file_count_within_limit(directory: Path, max_files: int) -> Validated[Path]:
    """
    Check directory doesn't exceed file count limit (lazy counting).
    
    WHY:
    - Prevents denial-of-service from huge directories
    - Lazy counting stops early for efficiency
    - Memory efficient for large directories
    """
    try:
        count = 0
        for p in directory.iterdir():
            if p.is_file():
                count += 1
                if count > max_files:  # Stop early for efficiency
                    return Validated(None, [ValidationError(f"Exceeds {max_files} files")])
        return Validated(directory)
    except OSError as e:
        return Validated(None, [ValidationError(f"Cannot access directory: {e}")])


def validate_within_base(path: Path, base_dir: Path) -> Validated[Path]:
    """
    Path traversal defense: ensure path stays within allowed base directory.
    
    SECURITY: Critical for user-provided paths!
    Prevents attacks like "../../../etc/passwd"
    """
    try:
        resolved = path.resolve()
        if not resolved.is_relative_to(base_dir):
            return Validated(None, [ValidationError(f"Path outside allowed area: {path}")])
        return Validated(resolved)
    except Exception as e:
        return Validated(None, [ValidationError(f"Invalid path: {str(e)}")])


def validate_not_symlinks(path: Path) -> Validated[Path]:
    """
    Check if path or any parent is a symlink.
    
    SECURITY: Symlink attack prevention.
    Symlinks can redirect operations to unexpected locations.
    """
    current = path
    while current != current.parent:  # Stop at root
        if current.is_symlink():
            return Validated(None, [ValidationError(f"Symlink in path: {current}")])
        current = current.parent
    return Validated(path)


def validate_is_writable_secure(p: Path) -> Validated[Path]:
    """
    Secure writable check with TOCTOU (Time-Of-Check-Time-Of-Use) mitigation.
    
    WHY TOCTOU MATTERS:
    - Between checking permission and using it, permissions could change
    - Malicious processes could replace directories with symlinks
    - Solution: Test by actually creating a file with unique name
    
    SECURITY FEATURES:
    1. Unpredictable test filename (prevents pre-creation attacks)
    2. exist_ok=False (ensures WE create it)
    3. Cleanup after test
    """
    
    # 1. If directory exists, test writing
    if p.exists():
        if not p.is_dir():
            return Validated(None, [ValidationError(f"Not a directory: {p}")])
        
        # Create unpredictable test filename
        test_name = f".write_test_{os.getpid()}_{int(time.time())}_{os.urandom(4).hex()}"
        test_file = p / test_name
        
        try:
            # Use exist_ok=False to ensure WE create it
            test_file.touch(exist_ok=False)
            test_file.unlink(missing_ok=True)
            return Validated(p)
        except FileExistsError:
            # Extremely unlikely collision, but handle
            return Validated(None, [ValidationError(f"Test file collision (retry): {p}")])
        except PermissionError:
            return Validated(None, [ValidationError(f"No write permission: {p}")])
    
    # 2. If directory doesn't exist, check if parent is writable
    else:
        parent = p.parent
        if not parent.exists():
            return Validated(None, [ValidationError(f"Parent doesn't exist: {parent}")])
        
        # Recursively check parent
        return validate_is_writable_secure(parent)

# =============================================================================
# COMPOSED PARSERS - Business rules from atomic validators
# =============================================================================

def parse_source_directory_secure(path: Path, max_files: int = 10000) -> Validated[Path]:
    """
    SECURE version: Validate security constraints FIRST.
    Business rule: "Is this path a valid source directory for organization?"
    
    VALIDATION ORDER MATTERS:
    1. Security (path traversal) - Fail fast on dangerous paths
    2. Existence - Don't proceed if path doesn't exist
    3. Type - Must be a directory
    4. Permissions - Must be readable
    5. Size limits - Prevent denial-of-service
    """
    # Pre-fill functions with parameters using partial
    check_file_limit = partial(validate_file_count_within_limit, max_files=max_files)
    
    return (
        validate_within_base(path, Path.home())  # 🔐 SECURITY FIRST
        .bind(validate_path_exists)              # Must exist
        .bind(validate_is_directory)             # Must be directory
        .bind(validate_is_readable)              # Must be readable
        .bind(check_file_limit)                  # Must not exceed file limit
    )


def parse_backup_source(path: Path) -> Validated[Path]:
    """
    Business rule: "Is this path suitable for backup operations?"
    
    DIFFERENCE FROM parse_source_directory_secure:
    - Backup source needs read access (to copy files)
    - Doesn't need to be within home directory (could backup external drives)
    - Still validates existence and directory type
    """
    return (
        validate_path_exists(path)
        .bind(validate_is_directory)
        .bind(validate_is_readable)
    )


def parse_backup_destination(path: Path) -> Validated[Path]:
    """
    Secure destination directory validation.
    Validates write access WITHOUT granting read access (principle of least privilege).
    
    SECURITY PRINCIPLES:
    - Destination needs WRITE, not READ
    - No symlinks allowed (prevents symlink attacks)
    - Can create directory if doesn't exist (checks parent permissions)
    """
    
    def parse_directory_or_creatable(p: Path) -> Validated[Path]:
        """
        Check if directory exists or can be created.
        If doesn't exist, check if parent is writable.
        """
        if p.exists():
            return validate_is_directory(p)  # Must be directory if exists
        else:
            # Check if parent directory exists and is writable
            parent_validation = validate_path_exists(p.parent).bind(validate_is_writable_secure)
            if parent_validation.is_valid:
                return Validated(p)  # Can be created
            return Validated(None, [ValidationError(f"Cannot create directory: {p}")])
    
    return (
        validate_within_base(path, Path.home())      # 🛡️ Security boundary
        .bind(parse_directory_or_creatable)          # Exists or can be created
        .bind(validate_not_symlinks)                 # 🛡️ No symlinks
        .bind(validate_is_writable_secure)           # ✅ WRITE permission
    )


def parse_conflict_strategy(value: str) -> Validated[ConflictStrategy]:
    """
    Parse and validate conflict strategy from string.
    
    SECURITY: Basic input sanitization
    - Removes whitespace
    - Converts to lowercase
    - Checks for alphanumeric only (blocks shell injection)
    """
    try:
        # Basic sanitization
        clean_value = value.strip().lower()
        if not clean_value.isalnum():
            return Validated(None, [ValidationError("Invalid characters in strategy")])
        
        strategy = ConflictStrategy(clean_value)
        return Validated(strategy)
    except ValueError:
        valid_options = ", ".join(s.value for s in ConflictStrategy)
        return Validated(None, [ValidationError(f"Invalid strategy '{value}'. Choose from: {valid_options}")])
    except Exception:
        return Validated(None, [ValidationError(f"Invalid input")])


# =============================================================================
# CONFIGURATIONS & DOMAIN MODELS
# =============================================================================

@dataclass(frozen=True)
class AppConfig:
    app_name: str = "organizer"
    app_author: str = "Al-Azeem"
    max_files: int = 10000
    backup_retry_attempts: int = 2


APP_CONFIG = AppConfig()
APP_DIRS = PlatformDirs(APP_CONFIG.app_name, APP_CONFIG.app_author)
MAX_FILES: int = APP_CONFIG.max_files
BACKUP_DIR: Path = Path(APP_DIRS.user_data_dir) / "backups"
LOG_DIR: Path = Path(APP_DIRS.user_log_dir)
STATE_DIR: Path = Path(APP_DIRS.user_state_dir)
ORGANIZE_STATE_PATH: Path = STATE_DIR / "organize_state.json"


class ConflictStrategy(Enum):
    """Strategies for handling file name conflicts."""
    SKIP = "skip"        # Skip conflicted files
    RENAME = "rename"    # Rename conflicted files
    OVERWRITE = "overwrite"  # Overwrite target files
    DELETE = "delete"    # Delete source conflicted files


@dataclass
class FileInfo:
    """Metadata container for a single file."""
    path: Path           # Full path to file
    name: str            # File name with extension
    stem: str            # File name without extension
    suffix: str          # Extension with dot
    category: str        # Directory derived from suffix
    size: int = 0        # File size in bytes
    permission: int | None = None  # File permissions
    created: datetime | None = None  # Creation timestamp
    modified: datetime | None = None  # Modification timestamp


@dataclass
class OrganizationResult:
    """Results container for organization operations."""
    organized: int = 0                     # Files successfully organized
    skipped: int = 0                       # Files skipped (already in correct location)
    conflicts: int = 0                     # Files with name conflicts
    errors: int = 0                        # Files that failed with errors
    created_categories_count: int = 0      # New categories created
    operations: List[Tuple[Path, Path]] = field(default_factory=list)  # Move operations
    discovered_categories: Set[str] = field(default_factory=set)  # All categories found


@dataclass(frozen=True)
class OrganizeFilesInput:
    source_dir: Path
    dry_run: bool = True
    conflict_strategy: ConflictStrategy = ConflictStrategy.SKIP
    recursive: bool = False
    max_files: int = MAX_FILES
    backup: bool = False


@dataclass(frozen=True)
class BackupCommandInput:
    source_dir: Path
    backup_dir: Path = BACKUP_DIR
    compress: bool = True
    compression_format: str = "zip"


@dataclass(frozen=True)
class DirectoryAnalysis:
    source_dir: Path
    file_count: int
    category_counts: dict[str, int]

    @property
    def categories(self) -> list[str]:
        return sorted(self.category_counts)


@dataclass
class OrganizeOperationState:
    source_dir: str
    conflict_strategy: str
    recursive: bool
    max_files: int
    started_at: str
    completed_paths: list[str] = field(default_factory=list)

# =============================================================================
# CORE UTILITIES - Single responsibility functions
# =============================================================================

def _setup_env() -> Path:
    """Create organizer storage directories and return the log file path."""
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
    except PermissionError as e:
        logger.error(
            f"Cannot create directories. "
            f"Check write permissions for: {BACKUP_DIR.parent} and {LOG_DIR}"
        )
        raise PermissionError(f"Directory creation failed: {e}")
    return LOG_DIR / "organizer.log"


def _setup_logger(log_file: Path) -> None:
    """Setup dual logging: console for users, file for debugging."""
    file_level = "DEBUG"
    user_level = "INFO"
    
    logger.remove()
    
    # Console logging (user-friendly)
    logger.add(
        sink=sys.stderr,
        level=user_level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
        colorize=True,
        backtrace=True,
        catch=True
    )
    
    # File logging (detailed, for debugging)
    log_file = LOG_DIR / "organizer.log"
    logger.add(
        sink=str(log_file),
        level=file_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {module}.{function}:{line} | {message}",
        rotation="10 MB",
        retention="30 days",
        compression="gz",
        serialize=True,
        enqueue=True,
        backtrace=True,
        catch=True,
    )


def extract_file_category(
    file_path: Path, 
    *, 
    custom_mapping: dict[str, str] | None = None
) -> str:
    """
    Generate safe directory name from file extension with compound extension support.
    
    FEATURES:
    - Handles compound extensions (.tar.gz, .tar.bz2)
    - Custom mapping overrides built-in categories
    - Sanitizes unsafe characters in category names
    - Special handling for hidden files
    """
    
    # Handle None case
    if custom_mapping is None:
        custom_mapping = {}
    
    # Hidden files
    if file_path.name.startswith("."):
        return "hidden"
    
    # Get all suffixes for compound extensions
    file_suffixes = file_path.suffixes  # Returns ['.tar', '.gz'] for .tar.gz
    if not file_suffixes:
        return "no_extension"
    
    # Build full extension (e.g., '.tar.gz') and last extension (e.g., '.gz')
    # YOUR VERSION - SIMPLEST AND BEST
    compound_extension = ''.join(file_suffixes).lower().replace('.', '')
    last_extension = file_suffixes[-1].lower() if file_suffixes else ""
    
    # Priority 1: custom mapping (check full extension first, then last)
    if compound_extension in custom_mapping:
        return custom_mapping[compound_extension]
    if last_extension in custom_mapping:
        return custom_mapping[last_extension]
    
    # Built-in categories with compound extension support
    CATEGORY_MAP = {
        # Media
        ".mp4": "movies", ".avi": "movies", ".mkv": "movies", 
        ".mov": "movies", ".wmv": "movies", ".flv": "movies",
        ".webm": "movies", ".m4v": "movies",
        
        ".mp3": "music", ".wav": "music", ".flac": "music",
        ".m4a": "music", ".ogg": "music", ".aac": "music",
        ".wma": "music", ".opus": "music",
        
        ".jpg": "images", ".jpeg": "images", ".png": "images",
        ".gif": "images", ".webp": "images", ".bmp": "images",
        ".tiff": "images", ".svg": "images", ".ico": "images",
        ".heic": "images", ".raw": "images",
        
        # Documents
        ".pdf": "documents",
        ".doc": "documents", ".docx": "documents",
        ".txt": "documents", ".rtf": "documents",
        ".odt": "documents", ".md": "documents",
        ".pages": "documents",
        
        # Spreadsheets
        ".xls": "spreadsheets", ".xlsx": "spreadsheets",
        ".ods": "spreadsheets", ".csv": "spreadsheets",
        
        # Presentations
        ".ppt": "presentations", ".pptx": "presentations",
        ".odp": "presentations", ".key": "presentations",
        
        # Archives - singles and compounds
        ".zip": "archives", ".tar": "archives",
        ".rar": "archives", ".7z": "archives", 
        ".bz2": "archives", ".gz": "archives",
        
        # Compound archives
        ".tar.gz": "archives", ".tar.bz2": "archives", 
        ".tar.xz": "archives", ".tgz": "archives",
        
        # Code
        ".py": "code", ".js": "code", ".java": "code",
        ".cpp": "code", ".c": "code", ".html": "code",
        ".css": "code", ".json": "code", ".xml": "code",
        ".yaml": "code", ".yml": "code", ".toml": "code",
        ".ini": "code", ".cfg": "code", ".conf": "code",
        
        # Executables
        ".exe": "executables", ".msi": "executables",
        ".app": "executables", ".sh": "executables",
        ".bat": "executables", ".cmd": "executables",
    }
    
    # Priority 2: Built-in mapping (check full compound extension first, then last)
    if compound_extension in CATEGORY_MAP:
        return CATEGORY_MAP[compound_extension]
    if last_extension in CATEGORY_MAP:
        return CATEGORY_MAP[last_extension]
    
    # Fallback: For unknown extensions
    if len(file_suffixes) > 1:
        # Compound extension: join without dots and sanitize
        base_category = ''.join(s.lstrip('.') for s in file_suffixes)
    else:
        # Single extension
        base_category = last_extension.lstrip(".")
    
    # Sanitize to make safe folder name
    category = re.sub(r"[^\w\-]", "_", base_category)
    
    # Ensure non-empty category
    if not category or category.isspace():
        return "misc"
    return category.strip()


def gather_file_metadata(file_path: Path) -> FileInfo:
    """Extract comprehensive metadata from a file."""
    
    # Assert operational invariants
    if not file_path.is_file():
        raise ValidationError(f"Not a file: {file_path}")
    
    try:
        stat = file_path.stat()
    except (PermissionError, OSError) as e:
        raise ValidationError(f"Cannot read file metadata: {e}") from e
    
    return FileInfo(
        path=file_path,
        name=file_path.name,
        stem=file_path.stem,
        suffix=file_path.suffix,
        category=extract_file_category(file_path),
        size=stat.st_size,
        permission=stat.st_mode,
        created=datetime.fromtimestamp(stat.st_ctime),
        modified=datetime.fromtimestamp(stat.st_mtime),
    )


def generate_unique_filename(target_path: Path, max_attempts: int = 1000) -> Path:
    """
    Create unique filename by appending counter.
    
    Example: "file.txt" → "file_1.txt" → "file_2.txt"
    """
    counter = 1
    parent = target_path.parent
    stem, suffix = target_path.stem, target_path.suffix
    
    while counter <= max_attempts:
        new_name = parent / f"{stem}_{counter}{suffix}"
        if not new_name.exists():
            return new_name
        counter += 1
    
    raise RuntimeError(f"Could not generate unique name after {max_attempts} attempts")

# =============================================================================
# FILE COPY UTILITIES - Secure with progress tracking
# =============================================================================

def _copy_single_file_secure(src_file: Path, src_root: Path, dst_root: Path) -> int:
    """
    Copy a single file with retry logic and comprehensive error handling.
    
    SECURITY FEATURES:
    1. Verifies file is under source root (prevents symlink escapes)
    2. Retry logic for transient errors
    3. Size verification after copy
    4. Cleanup of partial files on failure
    
    DESIGN:
        - Retry up to 3 times with exponential backoff
        - Verify copy succeeded by checking file size
        - Preserve all file metadata (timestamps, permissions)
    """
    # Calculate destination path while preserving directory structure
    try:
        relative_path = src_file.relative_to(src_root)
    except ValueError:
        raise ValidationError(
            f"Security violation: File {src_file} is not under source root {src_root}"
        )
    
    # Construct full destination path
    dest_file = dst_root / relative_path
    
    # Ensure parent directory exists
    dest_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Get source file size for verification
    try:
        file_size = src_file.stat().st_size
    except OSError as e:
        raise PermissionError(f"Cannot read source file {src_file.name}: {e}")
    
    # Retry loop for transient errors
    last_error = None
    for attempt in range(3):
        try:
            # Copy with metadata preservation
            shutil.copy2(src_file, dest_file)
            
            # Verification: Ensure copy succeeded completely
            if not dest_file.exists():
                raise OSError(f"Target file not created after copy operation")
            
            # Verify copied file size matches source
            copied_size = dest_file.stat().st_size
            if copied_size != file_size:
                # Partial copy detected - delete and retry
                dest_file.unlink(missing_ok=True)
                raise OSError(
                    f"Copy incomplete: {copied_size:,} of {file_size:,} bytes transferred"
                )
            
            # SUCCESS: File copied completely and verified
            return file_size
            
        except (OSError, IOError, PermissionError) as e:
            last_error = e
            
            # Cleanup: Remove any partial file
            dest_file.unlink(missing_ok=True)
            
            if attempt < 2:  # Not the last attempt
                # Exponential backoff
                sleep_time = 0.1 * ((attempt + 1) ** 2)
                logger.debug(
                    f"Retry {attempt + 1}/3 for {src_file.name}: "
                    f"{e}, waiting {sleep_time:.1f}s"
                )
                time.sleep(sleep_time)
            else:
                logger.debug(f"Final copy attempt failed for {src_file.name}: {e}")
    
    # All retry attempts failed
    raise last_error or OSError(f"Unknown error copying {src_file.name}")

# =============================================================================
# VALIDATION
# =============================================================================

def _validate_paths(src_dir: Path, dst_dir: Path) -> None:
    """Validate source and destination directories."""
    source_validation = parse_backup_source(src_dir)
    if source_validation.is_invalid:
        error_messages = "\n".join(str(e) for e in source_validation.errors)
        raise ValidationError(f"Invalid source directory:\n{error_messages}")
    
    dest_validation = parse_backup_destination(dst_dir)
    if dest_validation.is_invalid:
        error_messages = "\n".join(str(e) for e in dest_validation.errors)
        raise ValidationError(f"Invalid destination directory:\n{error_messages}")
    
    logger.debug(f"Security validation passed: {src_dir} → {dst_dir}")


def copy_directory_with_progress_secure(src_dir: Path, dst_dir: Path) -> int:
    """
    Securely copy directory contents with streaming architecture.
    """
    
    # =========================================================================
    # PHASE 1: VALIDATION
    # =========================================================================
    _validate_paths(src_dir, dst_dir)

    
    # =========================================================================
    # PHASE 2: ESTIMATION
    # =========================================================================
    is_terminal = sys.stderr.isatty()
    min_files = _estimate_files(src_dir) if is_terminal else 0
    
    if min_files == 0 and is_terminal:
        logger.info("No files found")
        return 0
    if is_terminal:
        logger.info(f"Found at least {min_files:,} files")
    
    # =========================================================================
    # PHASE 3: COPY
    # =========================================================================
    logger.info(f"Starting streaming copy from {src_dir} to {dst_dir}")
    start_time = datetime.now()
    
    # Check for tqdm
    has_tqdm = _check_tqdm(is_terminal)
    
    # Initialize counters
    stats = {
        'total_items': 0,
        'processed': 0,
        'copied': 0,
        'skipped': 0,
        'bytes': 0,
    }
    
    try:
        if has_tqdm and min_files > 0:
            _copy_with_tqdm(src_dir, dst_dir, min_files, start_time, stats)
        else:
            _copy_simple(src_dir, dst_dir, min_files, start_time, stats, is_terminal)
        
        if stats['processed'] == 0:
            logger.info(f"No files found in {src_dir}")
            return 0
            
    except KeyboardInterrupt:
        _handle_interrupt(start_time, stats)
        raise
    except Exception as e:
        _handle_error(start_time, e)
        raise
    
    # =========================================================================
    # PHASE 4: REPORTING
    # =========================================================================
    _report_results(start_time, stats, src_dir, dst_dir)
    
    return stats['copied']


# =============================================================================
# ESTIMATION
# =============================================================================

def _estimate_files(directory: Path, limit: int = 1000) -> int:
    """Return number of files found up to limit."""
    count = 0
    for item in directory.rglob("*"):
        if item.is_file():
            count += 1
            if count >= limit:
                break
    return count


# =============================================================================
# PROGRESS UI
# =============================================================================

def _check_tqdm(is_terminal: bool) -> bool:
    """Check if tqdm is available and should be used."""
    if not is_terminal:
        logger.debug("tqdm not available")
    return False
    # or return tqdm

def _update_display(stats: dict, start: datetime, min_files: int) -> str:
    """Generate progress display string."""
    elapsed = (datetime.now() - start).total_seconds()
    rate = stats['processed'] / elapsed if elapsed > 0 else 0
    mb = stats['bytes'] / (1024 * 1024)
    return f"📁 {stats['copied']:,} / at least {min_files:,} | {mb:.0f} MB | {rate:.0f}/sec"


# =============================================================================
# SAFETY
# =============================================================================

def _check_safety(total_items: int, start: datetime) -> None:
    """Raise ValidationError if safety limit exceeded."""
    SAFETY_LIMIT = 1_000_000
    if total_items <= SAFETY_LIMIT:
        return
    elapsed = (datetime.now() - start).total_seconds()
    raise ValidationError(
        f"Safety limit exceeded: {total_items:,} > {SAFETY_LIMIT:,} items.\n"
        f"Processed for {elapsed:.1f}s before hitting limit."
    )


# =============================================================================
# COPY OPERATIONS
# =============================================================================

def _copy_one_file(item: Path, src_dir: Path, dst_dir: Path, stats: dict) -> None:
    """Copy a single file, update stats."""
    try:
        bytes_copied = _copy_single_file_secure(item, src_dir, dst_dir)
        stats['copied'] += 1
        stats['bytes'] += bytes_copied
    except Exception as e:
        logger.warning(f"Failed to copy {item.name}: {e}")
        stats['skipped'] += 1
    finally:
        stats['processed'] += 1


def _copy_with_tqdm(src_dir: Path, dst_dir: Path, min_files: int, 
                    start: datetime, stats: dict) -> None:
    """Copy with tqdm progress bar."""
    
    with tqdm(total=min_files, desc="📁 Copying", unit="files") as pbar:
        for item in src_dir.rglob("*"):
            stats['total_items'] += 1
            _check_safety(stats['total_items'], start)
            
            if not item.is_file():
                continue
            
            _copy_one_file(item, src_dir, dst_dir, stats)
            pbar.update(1)
            
            if stats['processed'] % 100 == 0:
                pbar.set_description(_update_display(stats, start, min_files))


def _copy_simple(src_dir: Path, dst_dir: Path, min_files: int,
                 start: datetime, stats: dict, is_terminal: bool) -> None:
    """Copy with simple print progress."""
    for item in src_dir.rglob("*"):
        stats['total_items'] += 1
        _check_safety(stats['total_items'], start)
        
        if not item.is_file():
            continue
        
        _copy_one_file(item, src_dir, dst_dir, stats)
        
        if is_terminal and stats['copied'] % 100 == 0:
            print(f"\r{_update_display(stats, start, min_files)}", 
                  end="", flush=True)
    
    if is_terminal and stats['copied'] > 0:
        print()


# =============================================================================
# ERROR HANDLING
# =============================================================================

def _handle_interrupt(start: datetime, stats: dict) -> None:
    """Handle KeyboardInterrupt gracefully."""
    elapsed = (datetime.now() - start).total_seconds()
    logger.warning(
        f"\n⚠️  Copy interrupted after {elapsed:.1f}s\n"
        f"   Copied: {stats['copied']:,} files\n"
        f"   Failed: {stats['skipped']:,} files"
    )


def _handle_error(start: datetime, error: Exception) -> None:
    """Handle general errors."""
    elapsed = (datetime.now() - start).total_seconds()
    logger.error(f"Copy failed after {elapsed:.1f}s: {error}")


# =============================================================================
# REPORTING
# =============================================================================

def _report_results(start: datetime, stats: dict, src_dir: Path, dst_dir: Path) -> None:
    """Log final results and metrics."""
    elapsed = (datetime.now() - start).total_seconds()
    gb = stats['bytes'] / (1024 * 1024 * 1024)
    rate = stats['copied'] / elapsed if elapsed > 0 else 0
    byte_rate = stats['bytes'] / elapsed if elapsed > 0 else 0
    
    # Success message
    logger.success(
        f"\n{'='*60}\n"
        f"✅ COPY COMPLETE\n"
        f"{'='*60}\n"
        f"   Files copied:  {stats['copied']:,}\n"
        f"   Files failed:  {stats['skipped']:,}\n"
        f"   Total data:    {gb:.2f} GB\n"
        f"   Copy time:     {elapsed:.1f}s\n"
        f"   Speed:         {rate:.1f} files/sec, {byte_rate/1024/1024:.1f} MB/sec"
    )
    
    # Security audit
    logger.debug(
        f"\nSECURITY AUDIT LOG\n"
        f"  Source: {src_dir} (READ permission)\n"
        f"  Destination: {dst_dir} (WRITE permission)\n"
        f"  Items scanned: {stats['total_items']:,}\n"
        f"  Files copied: {stats['copied']:,}\n"
        f"  Files failed: {stats['skipped']:,}"
    )
    
    # Failure analysis
    _report_failures(stats)


def _report_failures(stats: dict) -> None:
    """Log warnings for high failure rates."""
    if stats['skipped'] == 0 or stats['processed'] == 0:
        return
    
    failure_rate = (stats['skipped'] / stats['processed']) * 100
    
    if failure_rate > 20:
        logger.error(
            f"\n⚠️  HIGH FAILURE RATE: {failure_rate:.1f}% ({stats['skipped']:,} files)\n"
            f"   Check: permissions, disk space, file locks"
        )
    elif failure_rate > 5:
        logger.warning(f"\n⚠️  {failure_rate:.1f}% failed ({stats['skipped']:,} files)")
    else:
        logger.info(f"\nNote: {stats['skipped']:,} files skipped")

# =============================================================================
# COMPRESSION UTILITIES
# =============================================================================

def compress_to_zip(source_dir: Path, archive_path: Path) -> bool:
    """Compress directory to ZIP format."""
    try:
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file_path in source_dir.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(source_dir)
                    zipf.write(file_path, arcname)
        return True
    except Exception as e:
        logger.error(f"ZIP compression failed: {e}")
        if archive_path.exists():
            archive_path.unlink(missing_ok=True)
        return False


def compress_to_tar_gz(source_dir: Path, archive_path: Path) -> bool:
    """Compress directory to TAR.GZ format."""
    try:
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(source_dir, arcname=source_dir.name)
        return True
    except Exception as e:
        logger.error(f"TAR.GZ compression failed: {e}")
        if archive_path.exists():
            archive_path.unlink(missing_ok=True)
        return False

# =============================================================================
# DECORATORS - Cross-cutting concerns
# =============================================================================

def with_logging(func: Callable) -> Callable:
    """Decorator for automatic logging of function entry and exit."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        logger.debug(f"Starting {func.__name__}")
        try:
            result = func(*args, **kwargs)
            logger.debug(f"Completed {func.__name__}")
            return result
        except Exception as e:
            logger.error(f"{func.__name__} failed: {e}")
            raise
    return wrapper


def with_retry(max_attempts: int = 3):
    """Decorator for automatic retry logic with exponential backoff."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        logger.warning(f"Attempt {attempt + 1} failed, retrying...")
            raise last_exception or RuntimeError("All retry attempts failed")
        return wrapper
    return decorator

# =============================================================================
# DISK SPACE MANAGEMENT - Critical for backup operations
# =============================================================================

class DiskSpaceManager:
    """
    Manages disk space checks and monitoring for backup operations.
    
    WHY DISK SPACE MANAGEMENT IS CRITICAL:
    1. Prevents data corruption from partial backups
    2. Provides clear error messages before starting long operations
    3. Prevents system instability from disk exhaustion
    4. Allows user to make informed decisions about backup locations
    """
    
    BUFFER_PERCENT = 20  # 20% buffer for safety (filesystem overhead, temp files)
    MIN_FREE_PERCENT = 10  # Keep at least 10% free after backup
    
    @classmethod
    def check_space_for_backup(
        cls, 
        source_dir: Path, 
        destination_dir: Path,
        estimate_only: bool = False
    ) -> Tuple[bool, Optional[str], Optional[int]]:
        """
        Comprehensive disk space check for backup operations.
        
        Returns:
            (has_space, error_message, estimated_size_bytes)
            
        DESIGN:
            - Fast estimation mode for quick pre-checks
            - Accurate mode for final verification
            - Safety buffer included in calculations
            - Minimum free space requirement after backup
        """
        try:
            # 1. Estimate source size
            if estimate_only:
                source_size = cls._estimate_source_size_fast(source_dir)
            else:
                source_size = cls._calculate_source_size_accurate(source_dir)
            
            if source_size == 0:
                return True, "No files to backup", 0
            
            # 2. Get destination free space
            try:
                dst_usage = shutil.disk_usage(destination_dir)
                dst_free = dst_usage.free
                dst_total = dst_usage.total
            except OSError as e:
                logger.warning(f"Cannot get disk usage for {destination_dir}: {e}")
                return True, None, source_size  # Assume OK if we can't check
            
            # 3. Calculate required space with buffer
            required_space = source_size * (1 + cls.BUFFER_PERCENT / 100)
            
            # 4. Check if enough space
            if dst_free < required_space:
                needed_gb = required_space / (1024**3)
                free_gb = dst_free / (1024**3)
                total_gb = dst_total / (1024**3)
                
                return False, (
                    f"🚨 INSUFFICIENT DISK SPACE\n"
                    f"   Source size: {source_size/1024**3:.1f} GB\n"
                    f"   Required (with {cls.BUFFER_PERCENT}% buffer): {needed_gb:.1f} GB\n"
                    f"   Available: {free_gb:.1f} GB\n"
                    f"   Drive capacity: {total_gb:.1f} GB\n"
                    f"   Short by: {needed_gb - free_gb:.1f} GB"
                ), source_size
            
            # 5. Check if we'll leave enough free space after backup
            remaining_after_backup = dst_free - source_size
            min_required_free = dst_total * (cls.MIN_FREE_PERCENT / 100)
            
            if remaining_after_backup < min_required_free:
                warning_msg = (
                    f"⚠️  WARNING: Backup will leave only {remaining_after_backup/1024**3:.1f} GB free\n"
                    f"   Recommended minimum: {min_required_free/1024**3:.1f} GB\n"
                    f"   Consider freeing space or using different drive"
                )
                return True, warning_msg, source_size
            
            return True, None, source_size
            
        except Exception as e:
            logger.error(f"Disk space check failed: {e}")
            return True, None, None  # Assume OK on error
    
    @staticmethod
    def _estimate_source_size_fast(source_dir: Path) -> int:
        """Quick size estimation (sample 100 files)."""
        total = 0
        sample_count = 0
        
        for item in source_dir.rglob("*"):
            if item.is_file() and sample_count < 100:  # Sample 100 files
                try:
                    total += item.stat().st_size
                    sample_count += 1
                except OSError:
                    continue
        
        if sample_count == 0:
            return 0
        
        # Estimate total based on sample
        avg_file_size = total / sample_count
        total_files = sum(1 for _ in source_dir.rglob("*") if _.is_file())
        
        return int(avg_file_size * total_files)
    
    @staticmethod
    def _calculate_source_size_accurate(source_dir: Path) -> int:
        """Accurate size calculation (all files)."""
        total = 0
        file_count = 0
        
        for item in source_dir.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                    file_count += 1
                    
                    # Safety: Stop if taking too long
                    if file_count > 100000:  # 100k files max for accurate count
                        logger.warning(f"Large directory: estimating size after {file_count:,} files")
                        return DiskSpaceManager._estimate_source_size_fast(source_dir)
                        
                except OSError:
                    continue
        
        return total
    
    @classmethod
    def monitor_copy_progress(
        cls,
        destination_dir: Path,
        copied_so_far: int,
        next_file_size: int
    ) -> Tuple[bool, Optional[str]]:
        """
        Monitor disk space during copy operation.
        Call before copying each file.
        
        PREVENTS:
        - Copying file that won't fit
        - Disk exhaustion during operation
        - System instability
        """
        try:
            dst_usage = shutil.disk_usage(destination_dir)
            dst_free = dst_usage.free
            
            # Check if next file will fit
            if dst_free < next_file_size:
                return False, (
                    f"Disk full! Cannot copy {next_file_size/1024**2:.1f} MB file.\n"
                    f"Only {dst_free/1024**2:.1f} MB free remaining."
                )
            
            # Check if we're getting too low
            if dst_free < dst_usage.total * 0.05:  # Less than 5% free
                return True, (
                    f"⚠️  Low disk space: {dst_free/1024**3:.1f} GB remaining "
                    f"({dst_free/dst_usage.total*100:.0f}%)"
                )
            
            return True, None
            
        except OSError:
            return True, None  # Assume OK if we can't check

# =============================================================================
# BACKUP APPLICATION
# =============================================================================

MAX_BACKUP_FILES = 1_000_000


def _copy_backup_directory_with_space_monitoring(src_dir: Path, dst_dir: Path) -> int:
    dest_validation = parse_backup_destination(dst_dir)
    if dest_validation.is_invalid:
        error_messages = "\n".join(str(error) for error in dest_validation.errors)
        raise ValidationError(f"Invalid backup destination:\n{error_messages}")

    file_paths: list[Path] = []
    for item in src_dir.rglob("*"):
        if len(file_paths) > MAX_BACKUP_FILES:
            raise ValidationError(f"Directory too large (> {MAX_BACKUP_FILES:,} items)")
        if item.is_file():
            file_paths.append(item)

    if not file_paths:
        logger.info(f"No files to copy from {src_dir}")
        return 0

    logger.info(f"Copying {len(file_paths):,} files from {src_dir} to {dst_dir}")
    copied_files = 0
    copied_bytes = 0
    can_monitor_space = True

    try:
        shutil.disk_usage(dst_dir)
    except OSError:
        can_monitor_space = False
        logger.debug("Cannot monitor disk space during copy - proceeding without space checks")

    for file_path in file_paths:
        try:
            file_size = file_path.stat().st_size
        except OSError as error:
            logger.warning(f"Cannot get size for {file_path.name}: {error}")
            continue

        if can_monitor_space:
            can_copy, space_msg = DiskSpaceManager.monitor_copy_progress(dst_dir, copied_bytes, file_size)
            if not can_copy:
                raise ValidationError(
                    f"Disk space exhausted after copying {copied_bytes/1024**3:.1f} GB.\n"
                    f"Need {file_size/1024**3:.2f} GB more for {file_path.name}."
                )
            if space_msg:
                logger.warning(space_msg)

        try:
            bytes_copied = _copy_single_file_secure(file_path, src_dir, dst_dir)
        except Exception as error:
            logger.warning(f"Failed to copy {file_path.name}: {error}")
            continue

        copied_files += 1
        copied_bytes += bytes_copied

    return copied_files


def _compress_backup_directory(backup_dir: Path, compression_format: str) -> Path | None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        if compression_format == "zip":
            archive_path = backup_dir.parent / f"{backup_dir.name}_{timestamp}.zip"
            if compress_to_zip(backup_dir, archive_path):
                return archive_path
            return None
        if compression_format == "tar.gz":
            archive_path = backup_dir.parent / f"{backup_dir.name}_{timestamp}.tar.gz"
            if compress_to_tar_gz(backup_dir, archive_path):
                return archive_path
            return None
        raise ValidationError(f"Unsupported compression format: {compression_format}")
    except Exception as error:
        logger.error(f"Compression failed: {error}")
        return None


def _cleanup_failed_backup(backup_path: Path) -> None:
    if not backup_path.exists():
        return
    try:
        logger.debug(f"Cleaning up failed backup: {backup_path}")
        shutil.rmtree(backup_path, ignore_errors=True)
    except Exception as error:
        logger.warning(f"Could not clean up backup directory {backup_path}: {error}")


def _extract_zip_archive(archive_path: Path, extract_dir: Path) -> bool:
    try:
        with zipfile.ZipFile(archive_path, "r") as zip_file:
            zip_file.extractall(extract_dir)
        return True
    except Exception as error:
        logger.error(f"ZIP extraction failed: {error}")
        return False


def _extract_tar_gz_archive(archive_path: Path, extract_dir: Path) -> bool:
    try:
        with tarfile.open(archive_path, "r:gz") as tar_file:
            tar_file.extractall(extract_dir)
        return True
    except Exception as error:
        logger.error(f"TAR.GZ extraction failed: {error}")
        return False


@with_logging
@with_retry(max_attempts=APP_CONFIG.backup_retry_attempts)
def create_backup(input_data: BackupCommandInput) -> Path | None:
    logger.info(f"Starting backup of {input_data.source_dir}")
    source_validation = parse_backup_source(input_data.source_dir)
    if source_validation.is_invalid:
        error_messages = "\n".join(str(error) for error in source_validation.errors)
        raise ValidationError(f"Invalid backup source:\n{error_messages}")

    validated_source = _get_validated_value(source_validation, "Backup source")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = input_data.backup_dir / f"backup_{validated_source.name}_{timestamp}"

    try:
        has_space, error_msg, estimated_size = DiskSpaceManager.check_space_for_backup(
            validated_source,
            input_data.backup_dir,
            estimate_only=True,
        )
        if not has_space:
            raise ValidationError(f"Cannot create backup: {error_msg}")
        if error_msg:
            logger.warning(error_msg)
        if estimated_size:
            logger.info(f"Estimated backup size: {estimated_size/1024**3:.1f} GB")

        backup_path.mkdir(parents=True, exist_ok=True)
        files_copied = _copy_backup_directory_with_space_monitoring(validated_source, backup_path)
        if files_copied == 0:
            backup_path.rmdir()
            return None

        if input_data.compress:
            archive_path = _compress_backup_directory(backup_path, input_data.compression_format)
            if archive_path is not None:
                shutil.rmtree(backup_path, ignore_errors=True)
                return archive_path

        return backup_path
    except Exception as error:
        logger.error(f"Backup failed: {error}")
        _cleanup_failed_backup(backup_path)
        return None


def get_backups(backup_dir: Path) -> List[Path]:
    backups = []
    if backup_dir.exists():
        for item in backup_dir.iterdir():
            if item.name.startswith("backup_") or item.suffix in {".zip", ".tar.gz"}:
                backups.append(item)

    backups.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return backups


def restore_backup(backup_path: Path, restore_dir: Path, backup_dir: Path) -> bool:
    logger.info(f"Restoring backup {backup_path} to {restore_dir}")
    del backup_dir

    try:
        dest_validation = parse_backup_destination(restore_dir)
        if dest_validation.is_invalid:
            error_messages = "\n".join(str(error) for error in dest_validation.errors)
            raise ValidationError(f"Invalid restore directory:\n{error_messages}")

        has_space, error_msg, _ = DiskSpaceManager.check_space_for_backup(
            backup_path,
            restore_dir,
            estimate_only=True,
        )
        if not has_space:
            raise ValidationError(f"Cannot restore backup: {error_msg}")
        if error_msg:
            logger.warning(error_msg)

        if backup_path.suffix == ".zip":
            return _extract_zip_archive(backup_path, restore_dir)
        if backup_path.suffix == ".tar.gz":
            return _extract_tar_gz_archive(backup_path, restore_dir)
        if backup_path.is_dir():
            return _copy_backup_directory_with_space_monitoring(backup_path, restore_dir) > 0

        logger.error(f"Unsupported backup format: {backup_path}")
        return False
    except Exception as error:
        logger.error(f"Restore failed: {error}")
        return False

# =============================================================================
# FILE ORGANIZATION APPLICATION
# =============================================================================

def _save_organize_state(state: OrganizeOperationState) -> None:
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
    ORGANIZE_STATE_PATH.unlink(missing_ok=True)


def _get_file_iterator(source_dir: Path, recursive: bool) -> Iterator[Path]:
    if recursive:
        return (item for item in source_dir.rglob("*") if item.is_file())
    return (item for item in source_dir.iterdir() if item.is_file())


def _collect_files_for_organization(source_dir: Path, recursive: bool, max_files: int) -> list[Path]:
    return list(_get_file_iterator(source_dir, recursive))[:max_files]


def _resolve_target_path(target_path: Path, strategy: ConflictStrategy) -> Path | None:
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

    typer.echo(
        f"Resuming previous organize run from {existing_state.started_at}. "
        f"Already processed: {len(existing_state.completed_paths)} files."
    )
    return existing_state, set(existing_state.completed_paths)


def _mark_file_completed(
    state: OrganizeOperationState | None,
    completed_paths: set[str],
    relative_path: str,
) -> None:
    if state is None or relative_path in completed_paths:
        return
    completed_paths.add(relative_path)
    state.completed_paths.append(relative_path)
    _save_organize_state(state)


def _log_organize_results(result: OrganizationResult, dry_run: bool) -> None:
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


@with_logging
def organize_files(input_data: OrganizeFilesInput) -> tuple[OrganizationResult, Path | None]:
    validated_source = _validate_source_directory(input_data.source_dir, input_data.max_files)
    state, completed_paths = _prepare_resume_state(validated_source, input_data)
    result = OrganizationResult()
    created_categories: set[str] = set()
    all_files = _collect_files_for_organization(validated_source, input_data.recursive, input_data.max_files)

    if not all_files:
        logger.info("No files to organize")
        _clear_organize_state()
        return result, None

    pending_files = [
        file_path
        for file_path in all_files
        if input_data.dry_run
        or str(file_path.relative_to(validated_source)) not in completed_paths
    ]

    logger.info(f"Found {len(all_files)} files to organize")
    if state is not None and completed_paths:
        logger.info(f"Resuming with {len(pending_files)} files remaining")

    try:
        with tqdm(
            total=len(pending_files),
            desc="🏢 Organizing",
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
                except Exception as error:
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
    return result, None

# =============================================================================
# CLI INTERFACE - User-facing commands
# =============================================================================

app = typer.Typer(
    help="🏢 Production File Organizer with Backup System",
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]}
)


@app.callback()
def init() -> None:
    log_file = _setup_env()
    _setup_logger(log_file)


def _get_validated_value[T](validation: Validated[T], context: str = "") -> T:
    """
    Takes a Validated[T] and either returns the value (guaranteed non-None) 
    or exits with an error if invalid.
    """
    if validation.is_invalid:
        typer.echo(f"❌ {context} validation failed:" if context else "❌ Validation failed:")
        for error in validation.errors:
            typer.echo(f"  • {error}")
        sys.exit(1)
    
    value = validation.value
    if value is None:
        raise ValidationError(f"{context or 'Value'} unexpectedly None after validation")
    
    return value


def _prompt_for_conflict_strategy() -> ConflictStrategy:
    """Interactive prompt for conflict resolution strategy."""
    typer.echo("\n🔀 Conflict Resolution Strategy")
    typer.echo("─────────────────────────────")
    typer.echo("1. Skip duplicates (safe)")
    typer.echo("2. Rename duplicates (file.txt → file_1.txt)")
    typer.echo("3. Overwrite (dangerous - deletes target files)")
    typer.echo("4. Delete (dangerous - deletes source files)")
    typer.echo("5. Cancel operation")
    
    while True:
        choice = typer.prompt("Choose strategy (1-5)", default="1", show_choices=False).strip()
        
        if choice == "1":
            return ConflictStrategy.SKIP
        elif choice == "2":
            return ConflictStrategy.RENAME
        elif choice == "3":
            if typer.confirm("⚠️  WARNING: Overwrite will delete target duplicate files. Continue?"):
                return ConflictStrategy.OVERWRITE
            else:
                typer.echo("Please choose another strategy.")
                continue
        elif choice == "4":
            if typer.confirm("⚠️  WARNING: Delete will remove conflicted source files. Continue?"):
                return ConflictStrategy.DELETE
            else:
                typer.echo("Please choose another strategy.")
                continue
        elif choice == "5":
            raise typer.Abort("Operation cancelled by user.")
        else:
            typer.echo("Invalid choice. Please enter 1-5.")


def _validate_source_directory(source_dir: Path, max_files: int) -> Path:
    source_validation = parse_source_directory_secure(source_dir, max_files)
    return _get_validated_value(source_validation, "Source directory")


def _resolve_conflict_strategy(strategy: str, interactive: bool) -> ConflictStrategy:
    if interactive:
        return _prompt_for_conflict_strategy()
    strategy_validation = parse_conflict_strategy(strategy)
    return _get_validated_value(strategy_validation, "Conflict strategy")


def _confirm_destructive_organize_strategy(
    conflict_strategy: ConflictStrategy,
    dry_run: bool,
    backup_enabled: bool,
) -> bool:
    if dry_run:
        return backup_enabled

    if conflict_strategy == ConflictStrategy.DELETE:
        typer.echo("\n" + "!" * 40)
        typer.echo("⚠️  DELETE STRATEGY SELECTED")
        typer.echo("!" * 40)
        typer.echo("Conflicted source files will be PERMANENTLY DELETED!")

        if not typer.confirm("\nAre you sure you want to delete files?"):
            raise typer.Abort("Delete strategy cancelled by user.")

        if not backup_enabled:
            typer.echo("\n💡 STRONGLY RECOMMENDED: Backup before deleting files")
            if typer.confirm("Create backup before proceeding?"):
                return True
        return backup_enabled

    if conflict_strategy == ConflictStrategy.OVERWRITE:
        typer.echo("\n" + "!" * 50)
        typer.echo("⚠️  WARNING: OVERWRITE STRATEGY SELECTED")
        typer.echo("!" * 50)
        typer.echo("This will PERMANENTLY DELETE duplicate files!")

        if not typer.confirm("\nAre you ABSOLUTELY sure you want to continue?"):
            raise typer.Abort("Overwrite strategy cancelled by user.")

        if not backup_enabled:
            typer.echo("\n💡 RECOMMENDATION: Consider creating a backup")
            if typer.confirm("Create backup before proceeding?"):
                return True

    return backup_enabled


def _confirm_organize_execution(input_data: OrganizeFilesInput) -> None:
    if input_data.dry_run:
        return

    typer.echo("\n" + "=" * 50)
    typer.echo("🚀 EXECUTION SUMMARY")
    typer.echo("=" * 50)
    typer.echo(f"Source: {input_data.source_dir}")
    typer.echo(f"Strategy: {input_data.conflict_strategy.value}")
    typer.echo(f"Mode: {'Recursive' if input_data.recursive else 'Current folder only'}")
    typer.echo(f"Max files: {input_data.max_files}")
    typer.echo(f"Backup: {'✅ Yes' if input_data.backup else '❌ No'}")

    if not typer.confirm("\nProceed with file organization?"):
        raise typer.Abort("Operation cancelled by user.")


def analyze_directory(source_dir: Path, max_files: int) -> DirectoryAnalysis:
    validated_source = _validate_source_directory(source_dir, max_files)
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


@app.command()
def organize(
    source_dir: Path = typer.Argument(..., help="📁 Directory to organize"),
    dry_run: bool = typer.Option(
        True,
        help="🛡️ Preview changes (default) / Execute organization"
    ),
    strategy: str = typer.Option(
        "skip", 
        "--strategy", "-s",
        help="Conflict strategy: skip|rename|overwrite|delete (default: skip)"
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive", "-i", 
        help="🎯 Choose strategy interactively before execution"
    ),
    recursive: bool = typer.Option(
        False,
        "--recursive", "-r",
        help="📂 Process subdirectories"
    ),
    max_files: int = typer.Option(
        MAX_FILES,
        "--max-files",
        help=f"🛡️ Maximum files to process (default: {MAX_FILES})"
    ),
    backup: bool = typer.Option(
        False,
        "--backup", "-b",
        help="💾 Create backup before organizing"
    ),
) -> None:
    """
    🏢 Organize files into categorized folders.
    
    Default: Dry run (preview changes)
    Use --execute to run with efficient single-pass algorithm.
    """
    try:
        if interactive:
            typer.echo("\n" + "=" * 50)
            typer.echo("🏢 FILE ORGANIZER - Interactive Mode")
            typer.echo("=" * 50)

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
            typer.echo("\n💾 Creating backup...")
            backup_path = create_backup(
                BackupCommandInput(
                    source_dir=organize_input.source_dir,
                    backup_dir=BACKUP_DIR,
                    compress=True,
                    compression_format="zip",
                )
            )
            if backup_path:
                typer.echo(f"✅ Backup created: {backup_path}")
            else:
                typer.echo("⚠️  Backup creation failed")
                if not typer.confirm("Continue without backup?"):
                    sys.exit(1)

        _confirm_organize_execution(organize_input)

        result, _ = organize_files(organize_input)

        if organize_input.dry_run:
            typer.echo("\n🧪 DRY RUN MODE")
            typer.echo("No files will be modified.")
            completion_msg = "🧪 DRY RUN COMPLETE"
            completion_details = "No changes were made to your files."
        else:
            typer.echo("\n" + "=" * 50)
            typer.echo("🚀 EXECUTING FILE ORGANIZATION")
            typer.echo("=" * 50)
            typer.echo("• Single-pass efficient mode")
            typer.echo("• Batch conflict resolution")
            completion_msg = "✅ ORGANIZATION COMPLETE"
            completion_details = "Files have been organized successfully."
        
        typer.echo(f"\n📊 RESULTS:")
        typer.echo(f"  Organized: {result.organized}")
        typer.echo(f"  Skipped: {result.skipped}")
        typer.echo(f"  Conflicts: {result.conflicts}")
        typer.echo(f"  Errors: {result.errors}")
        
        if result.discovered_categories:
            categories = ", ".join(sorted(result.discovered_categories))
            typer.echo(f"  Categories: {categories}")
        
        if result.organized > 0 and not dry_run:
            typer.echo(f"\n✅ Successfully organized {result.organized} files!")
            if backup_path:
                typer.echo(f"💾 Backup available: {backup_path}")
        
        if result.conflicts > 0:
            typer.echo(f"\nℹ️  {result.conflicts} conflicts occurred.")
            if conflict_strategy == ConflictStrategy.SKIP:
                typer.echo("   (Files were skipped due to name conflicts)")
            elif conflict_strategy == ConflictStrategy.RENAME:
                typer.echo("   (Files were renamed to avoid conflicts)")
            elif conflict_strategy == ConflictStrategy.OVERWRITE:
                typer.echo("   (Duplicate target files were overwritten/deleted)")
            elif conflict_strategy == ConflictStrategy.DELETE:
                typer.echo("   (Conflicted source files were deleted)")
        
        typer.echo(f"\n{completion_msg}")
        typer.echo(completion_details)
            
    except ValidationError as e:
        typer.echo(f"❌ Validation Error: {e}")
        sys.exit(1)
    except typer.Abort as e:
        typer.echo(f"Operation cancelled: {e}")
        sys.exit(0)
    except Exception as e:
        typer.echo(f"❌ Error: {e}")
        sys.exit(1)


@app.command()
def backup(
    source_dir: Path = typer.Argument(..., help="📁 Directory to backup"),
    backup_dir: Path = typer.Option(
        BACKUP_DIR,
        "--backup-dir", "-d",
        help="💾 Directory to store backups"
    ),
    compress: bool = typer.Option(
        True,
        "--compress/--no-compress",
        help="🗜️ Compress backup (default: yes)"
    ),
    compression_format: str = typer.Option(
        "zip",
        "--format", "-f",
        help="📦 Compression format: zip or tar.gz (default: zip)"
    ),
    list_backups: bool = typer.Option(
        False,
        "--list", "-l",
        help="📋 List existing backups"
    ),
    restore: Optional[Path] = typer.Option(
        None,
        "--restore", "-r",
        help="🔄 Restore a specific backup"
    ),
    restore_to: Path = typer.Option(
        Path.cwd(),
        "--restore-to", "-t",
        help="📂 Directory to restore to (default: current directory)"
    ),
) -> None:
    """
    💾 Backup and restore files with disk space management.
    
    FEATURES:
        - Disk space checking before backup
        - Compression options (ZIP, TAR.GZ)
        - Progress tracking during backup
        - Secure validation of all paths
        - Backup listing and restoration
    """
    try:
        if list_backups:
            backups = get_backups(backup_dir)
            if not backups:
                typer.echo("No backups found.")
                return
            
            typer.echo(f"\n📋 Available backups in {backup_dir}:")
            for backup_path in backups:
                size = backup_path.stat().st_size
                modified = datetime.fromtimestamp(backup_path.stat().st_mtime)
                size_str = f"{size/1024/1024:.1f} MB" if size < 1024**3 else f"{size/1024**3:.2f} GB"
                typer.echo(f"  • {backup_path.name} ({size_str}, {modified:%Y-%m-%d %H:%M})")
            return
        
        if restore:
            if not restore.exists():
                typer.echo(f"❌ Backup not found: {restore}")
                sys.exit(1)
            
            typer.echo(f"\n🔄 Restoring backup: {restore.name}")
            typer.echo(f"   To: {restore_to}")
            
            if not typer.confirm("\nProceed with restore?"):
                raise typer.Abort("Restore cancelled by user.")
            
            success = restore_backup(restore, restore_to, backup_dir)
            if success:
                typer.echo(f"✅ Backup restored successfully to {restore_to}")
            else:
                typer.echo(f"❌ Backup restore failed")
                sys.exit(1)
            return
        
        typer.echo(f"\n💾 Creating backup of: {source_dir}")
        typer.echo(f"   To: {backup_dir}")
        typer.echo(f"   Compression: {compress} ({compression_format})")
        
        if not typer.confirm("\nProceed with backup?"):
            raise typer.Abort("Backup cancelled by user.")
        
        backup_path = create_backup(
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
            typer.echo(f"\n✅ Backup created successfully!")
            typer.echo(f"   Location: {backup_path}")
            typer.echo(f"   Size: {size_str}")
        else:
            typer.echo(f"❌ Backup creation failed")
            sys.exit(1)
            
    except ValidationError as e:
        typer.echo(f"❌ Validation Error: {e}")
        sys.exit(1)
    except typer.Abort as e:
        typer.echo(f"Operation cancelled: {e}")
        sys.exit(0)
    except Exception as e:
        typer.echo(f"❌ Error: {e}")
        sys.exit(1)


@app.command()
def analyze(
    source_dir: Path = typer.Argument(..., help="📁 Directory to analyze"),
    max_files: int = typer.Option(50000, help="🛡️ Maximum files to scan")
) -> None:
    """
    📊 Analyze directory structure without making changes.
    
    Shows what would happen if you organized the directory:
        - Number of files
        - Categories that would be created
        - File types found
    """
    try:
        analysis = analyze_directory(source_dir, max_files)
        typer.echo(f"\n📊 Analysis of: {analysis.source_dir}")
        typer.echo(f"  Total files: {analysis.file_count:,}")
        typer.echo(f"  Unique categories: {len(analysis.categories)}")
        
        if analysis.categories:
            typer.echo("\n  Categories that would be created:")
            for category in analysis.categories:
                count = analysis.category_counts.get(category, 0)
                percentage = (count / analysis.file_count * 100) if analysis.file_count > 0 else 0
                typer.echo(f"    • {category}/ - {count:,} files ({percentage:.1f}%)")
            
    except Exception as e:
        typer.echo(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    app()
