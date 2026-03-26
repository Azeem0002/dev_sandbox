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
import shutil
import zipfile
import tarfile
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Set, Tuple, Callable, Iterator, Optional
from functools import partial, wraps
from contextlib import contextmanager

import typer
from loguru import logger
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

MAX_FILES: int = 10000
BACKUP_DIR: Path = Path.home() / ".file_organizer" / "backups"
LOG_DIR: Path = Path.home() / ".file_organizer" / "logs"


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

# =============================================================================
# CORE UTILITIES - Single responsibility functions
# =============================================================================

def setup_logging() -> None:
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
        enqueue=True,
        backtrace=True,
        catch=True,
    )


def ensure_directories_exist() -> None:
    """Create required directories if they don't exist."""
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Directories ensured: {BACKUP_DIR}, {LOG_DIR}")
    except PermissionError as e:
        logger.error(
            f"Cannot create directories. "
            f"Check write permissions for: {BACKUP_DIR.parent} and {LOG_DIR}"
        )
        raise PermissionError(f"Directory creation failed: {e}")


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


@contextmanager
def with_dry_run(enabled: bool = True):
    """Context manager for dry-run mode (no actual changes)."""
    if enabled:
        logger.info("🧪 DRY RUN MODE - No changes will be made")
        original_move = shutil.move
        original_mkdir = Path.mkdir
        
        def dry_move(src, dst_dir):
            logger.info(f"WOULD move: {src} → {dst_dir}")
            return dst_dir
        
        def dry_mkdir(self, *args, **kwargs):
            logger.info(f"WOULD create directory: {self}")
            return self
        
        shutil.move = dry_move
        Path.mkdir = dry_mkdir
        
        try:
            yield
        finally:
            shutil.move = original_move
            Path.mkdir = original_mkdir
    else:
        yield


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
# BACKUP ORCHESTRATOR - Complete backup system with disk space management
# =============================================================================

class BackupOrchestrator:
    """
    Orchestrates backup operations with security and progress tracking.
    
    KEY FEATURES:
    1. Disk space management (pre-check and monitoring)
    2. Secure validation of all paths
    3. Compression options (ZIP, TAR.GZ)
    4. Progress tracking and comprehensive logging
    5. Cleanup on failure
    6. Backup listing and restoration
    
    DESIGN:
        - Single responsibility: Only handles backup operations
        - Validation-first: All inputs validated before any operations
        - Error isolation: One backup failure doesn't affect system
        - User feedback: Clear progress and completion messages
    """
    
    # Configuration constants
    MAX_FILES = 1_000_000  # Safety limit for file counting
    BACKUP_RETRY_ATTEMPTS = 2
    
    def __init__(self, backup_dir: Path = BACKUP_DIR):
        self.backup_dir = backup_dir
        self.disk_manager = DiskSpaceManager()
    
    @with_logging
    @with_retry(max_attempts=BACKUP_RETRY_ATTEMPTS)
    def create_backup(
        self,
        source_dir: Path,
        *,
        compress: bool = True,
        compression_format: str = "zip"
    ) -> Path | None:
        """
        Create a complete backup of source directory.
        
        STEPS:
        1. Validate source directory
        2. Check disk space BEFORE starting
        3. Create unique backup directory with timestamp
        4. Copy all files with progress tracking and space monitoring
        5. Optionally compress backup
        6. Return path to backup (directory or archive)
        
        SECURITY:
            - All paths validated before use
            - Symlink protection
            - Path traversal prevention
            - Principle of least privilege (read source, write destination)
        """
        logger.info(f"Starting backup of {source_dir}")
        
        # 1. Validate source
        source_validation = parse_backup_source(source_dir)
        if source_validation.is_invalid:
            error_messages = "\n".join(str(e) for e in source_validation.errors)
            raise ValidationError(f"Invalid backup source:\n{error_messages}")
        
        validated_source = source_validation.value
        if validated_source is None:
            raise ValidationError("Source validation returned None")
        
        # 2. Create unique backup directory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_name = f"backup_{validated_source.name}_{timestamp}"
        backup_path = self.backup_dir / backup_name
        
        try:
            # 3. Check disk space BEFORE creating anything
            has_space, error_msg, estimated_size = self.disk_manager.check_space_for_backup(
                validated_source, 
                self.backup_dir,
                estimate_only=True
            )
            
            if not has_space:
                raise ValidationError(f"Cannot create backup: {error_msg}")
            
            if error_msg:  # Warning but not fatal
                logger.warning(error_msg)
            
            if estimated_size:
                logger.info(f"Estimated backup size: {estimated_size/1024**3:.1f} GB")
            
            # Clean up if directory already exists (shouldn't happen with timestamp)
            if backup_path.exists():
                logger.warning(f"Cleaning existing backup directory: {backup_path}")
                shutil.rmtree(backup_path, ignore_errors=True)
            
            # Create backup directory
            backup_path.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Created backup directory: {backup_path}")
            
            # 4. Copy files with progress and space monitoring
            files_copied = self._copy_directory_with_space_monitoring(validated_source, backup_path)
            
            if files_copied == 0:
                logger.warning(f"No files copied from {validated_source}")
                # Delete empty backup directory
                backup_path.rmdir()
                return None
            
            logger.success(f"✅ Backup created: {backup_path} ({files_copied:,} files)")
            
            # 5. Optional compression
            if compress and files_copied > 0:
                archive_path = self._compress_backup(backup_path, compression_format)
                if archive_path:
                    # Remove uncompressed directory after successful compression
                    shutil.rmtree(backup_path, ignore_errors=True)
                    logger.info(f"✅ Compressed backup: {archive_path}")
                    return archive_path
            
            return backup_path
            
        except Exception as e:
            # Cleanup on failure
            logger.error(f"Backup failed: {e}")
            self._cleanup_failed_backup(backup_path)
            return None
    
    def _copy_directory_with_space_monitoring(self, src_dir: Path, dst_dir: Path) -> int:
        """
        Copy directory with continuous disk space monitoring.
        """
        # Validate destination
        dest_validation = parse_backup_destination(dst_dir)
        if dest_validation.is_invalid:
            error_messages = "\n".join(str(e) for e in dest_validation.errors)
            raise ValidationError(f"Invalid backup destination:\n{error_messages}")
        
        # Count files
        total_items = 0
        total_files = 0
        file_paths = []
        
        for item in src_dir.rglob("*"):
            total_items += 1
            if total_items > self.MAX_FILES:
                raise ValidationError(f"Directory too large (> {self.MAX_FILES:,} items)")
            
            if item.is_file():
                total_files += 1
                file_paths.append(item)
        
        if total_files == 0:
            logger.info(f"No files to copy from {src_dir}")
            return 0
        
        logger.info(f"Copying {total_files:,} files from {src_dir} to {dst_dir}")
        
        # Initialize ALL variables at the top - this is the key fix
        copied_files = 0
        skipped_files = 0
        total_bytes = 0
        copied_bytes = 0  # Initialize unconditionally right here
        can_monitor_space = False
        
        # Try to enable space monitoring
        try:
            dst_usage = shutil.disk_usage(dst_dir)
            dst_free = dst_usage.free
            can_monitor_space = True
            # Note: copied_bytes is already 0 from initialization above
        except:
            logger.debug("Cannot monitor disk space during copy - proceeding without space checks")
        
        # Copy each file with space check
        for file_path in file_paths:
            # Get file size
            try:
                file_size = file_path.stat().st_size
            except OSError as e:
                logger.warning(f"Cannot get size for {file_path.name}: {e}")
                skipped_files += 1
                continue
            
            # Check disk space before each file (if monitoring is enabled)
            if can_monitor_space:
                try:
                    can_copy, space_msg = self.disk_manager.monitor_copy_progress(
                        dst_dir, copied_bytes, file_size
                    )
                    
                    if not can_copy:
                        raise ValidationError(
                            f"Disk space exhausted after copying {copied_bytes/1024**3:.1f} GB.\n"
                            f"Need {file_size/1024**3:.2f} GB more for {file_path.name}.\n"
                            f"Backup incomplete - {len(file_paths) - copied_files} files remaining."
                        )
                    
                    if space_msg:
                        logger.warning(space_msg)
                except Exception as e:
                    logger.error(f"Disk space check failed: {e}")
                    # Continue without further space checks for this file
                    pass
            
            # Copy the file
            try:
                bytes_copied = _copy_single_file_secure(file_path, src_dir, dst_dir)
                copied_files += 1
                total_bytes += bytes_copied
                
                # Update copied bytes for next space check (if monitoring is enabled)
                if can_monitor_space:
                    copied_bytes += bytes_copied
                    
            except Exception as e:
                logger.warning(f"Failed to copy {file_path.name}: {e}")
                skipped_files += 1
        
        return copied_files
    
    def _compress_backup(self, backup_dir: Path, format: str = "zip") -> Path | None:
        """
        Compress backup directory to archive.
        
        SUPPORTED FORMATS:
            - zip: Cross-platform, good compression
            - tar.gz: Better compression for text files, preserves permissions
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        try:
            if format == "zip":
                archive_path = backup_dir.parent / f"{backup_dir.name}_{timestamp}.zip"
                if compress_to_zip(backup_dir, archive_path):
                    logger.info(f"✅ Compressed to ZIP: {archive_path}")
                    return archive_path
            elif format == "tar.gz":
                archive_path = backup_dir.parent / f"{backup_dir.name}_{timestamp}.tar.gz"
                if compress_to_tar_gz(backup_dir, archive_path):
                    logger.info(f"✅ Compressed to TAR.GZ: {archive_path}")
                    return archive_path
            else:
                logger.error(f"Unsupported compression format: {format}")
                return None
                
        except Exception as e:
            logger.error(f"Compression failed: {e}")
            return None
        
        return None
    
    def _cleanup_failed_backup(self, backup_path: Path) -> None:
        """
        Clean up partially created backup on failure.
        
        WHY SEPARATE FUNCTION?
        - Centralized cleanup logic
        - Can be extended (e.g., send notifications)
        - Consistent error handling
        """
        if backup_path.exists():
            try:
                logger.debug(f"Cleaning up failed backup: {backup_path}")
                shutil.rmtree(backup_path, ignore_errors=True)
            except Exception as e:
                logger.warning(f"Could not clean up backup directory {backup_path}: {e}")
    
    def list_backups(self) -> List[Path]:
        """List available backups in backup directory."""
        backups = []
        if self.backup_dir.exists():
            for item in self.backup_dir.iterdir():
                if item.name.startswith("backup_") or item.suffix in {".zip", ".tar.gz"}:
                    backups.append(item)
        
        backups.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return backups
    
    def restore_backup(self, backup_path: Path, restore_dir: Path) -> bool:
        """
        Restore backup to target directory.
        
        SUPPORTED BACKUP TYPES:
            - Directory backups (uncompressed)
            - ZIP archives (.zip)
            - TAR.GZ archives (.tar.gz)
        """
        logger.info(f"Restoring backup {backup_path} to {restore_dir}")
        
        try:
            # Validate restore directory
            dest_validation = parse_backup_destination(restore_dir)
            if dest_validation.is_invalid:
                error_messages = "\n".join(str(e) for e in dest_validation.errors)
                raise ValidationError(f"Invalid restore directory:\n{error_messages}")
            
            # Check disk space before restoring
            has_space, error_msg, _ = self.disk_manager.check_space_for_backup(
                backup_path, restore_dir, estimate_only=True
            )
            
            if not has_space:
                raise ValidationError(f"Cannot restore backup: {error_msg}")
            
            if error_msg:
                logger.warning(error_msg)
            
            # Extract based on backup type
            if backup_path.suffix == ".zip":
                return self._extract_zip(backup_path, restore_dir)
            elif backup_path.suffix == ".tar.gz":
                return self._extract_tar_gz(backup_path, restore_dir)
            elif backup_path.is_dir():
                # Directory backup - copy it
                return self._copy_directory_with_space_monitoring(backup_path, restore_dir) > 0
            else:
                logger.error(f"Unsupported backup format: {backup_path}")
                return False
                
        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return False
    
    def _extract_zip(self, archive_path: Path, extract_dir: Path) -> bool:
        """Extract ZIP archive."""
        try:
            with zipfile.ZipFile(archive_path, "r") as zipf:
                zipf.extractall(extract_dir)
            return True
        except Exception as e:
            logger.error(f"ZIP extraction failed: {e}")
            return False
    
    def _extract_tar_gz(self, archive_path: Path, extract_dir: Path) -> bool:
        """Extract TAR.GZ archive."""
        try:
            with tarfile.open(archive_path, "r:gz") as tar:
                tar.extractall(extract_dir)
            return True
        except Exception as e:
            logger.error(f"TAR.GZ extraction failed: {e}")
            return False

# =============================================================================
# FILE ORGANIZATION ORCHESTRATORS
# =============================================================================

class FileOrganizationOrchestrator:
    """
    Organizes files into categorized folders.
    
    FEATURES:
        - File categorization by extension
        - Conflict resolution strategies
        - Dry-run mode for testing
        - Progress tracking
        - Comprehensive error handling
    """
    
    @with_logging
    def organize_files(
        self,
        source_dir: Path,
        *,
        conflict_strategy: ConflictStrategy = ConflictStrategy.SKIP,
        dry_run: bool = False,
        recursive: bool = False,
        max_files: int = MAX_FILES
    ) -> OrganizationResult:
        """
        Organize files with dry-run support.
        
        DESIGN:
            - Validation-first approach
            - Isolated error handling per file
            - Progress tracking with tqdm
            - Dry-run mode for safe testing
        """
        # Validate the source directory
        source_validation = parse_source_directory_secure(source_dir, max_files)
        if source_validation.is_invalid:
            error_messages = "\n".join([str(e) for e in source_validation.errors])
            raise ValidationError(f"Invalid source directory:\n{error_messages}")
        
        validated_dir = source_validation.value
        if validated_dir is None:
            raise ValidationError("Parsed source directory returned None")
        
        result = OrganizationResult()
        created_categories: Set[str] = set()
        
        # Get all files to organize
        all_files = list(self._get_file_iterator(validated_dir, recursive))
        all_files = all_files[:max_files]
        
        if not all_files:
            logger.info("No files to organize")
            return result
        
        logger.info(f"Found {len(all_files)} files to organize")
        
        # Process each file
        with with_dry_run(dry_run):
            with tqdm(
                total=len(all_files), # total items. 100%
                desc="🏢 Organizing", # Text before bar
                unit="files",         # Unit names
                colour="blue",        # Bar colour
                bar_format="{l_bar}{bar:40}{r_bar}", # How bar looks
                ncols=80,   # Width in characters
                mininterval=0.1,  # Minimum update interval(seconds)
            ) as pbar:
                for file_path in all_files:
                    self._process_single_file(
                        file_path,
                        validated_dir,
                        conflict_strategy,
                        created_categories,
                        result,
                        dry_run
                    )
                    pbar.update(1)
        
        self._log_results(result, dry_run)
        return result
    
    def _get_file_iterator(self, source_dir: Path, recursive: bool) -> Iterator[Path]:
        """Get iterator for files based on recursive flag."""
        if recursive:
            return (f for f in source_dir.rglob("*") if f.is_file())
        else:
            return (f for f in source_dir.iterdir() if f.is_file())
    
    def _process_single_file(
        self, 
        file_path: Path, 
        source_dir: Path, 
        strategy: ConflictStrategy, 
        created_categories: Set[str], 
        result: OrganizationResult, 
        dry_run: bool
    ) -> None:
        """Process a single file with error isolation."""
        try:
            file_info = gather_file_metadata(file_path)
            result.discovered_categories.add(file_info.category)
            
            category_dir = source_dir / file_info.category
            if file_info.category not in created_categories and not category_dir.exists():
                if not dry_run:
                    category_dir.mkdir(exist_ok=True)
                    created_categories.add(file_info.category)
                    result.created_categories_count += 1
            
            # Skip if already in correct category
            if file_path.parent == category_dir:
                result.skipped += 1
                return
            
            target_path = category_dir / file_info.name
            if target_path.exists():
                target_path = self._resolve_conflict(target_path, strategy)
                if target_path is None:
                    result.conflicts += 1
                    return
            
            if not dry_run:
                shutil.move(str(file_path), str(target_path))
                result.operations.append((file_path, target_path))
            
            result.organized += 1
            
        except ValidationError as e:
            logger.error(f"Validation failed for {file_path.name}: {e}")
            result.errors += 1
        except Exception as e:
            logger.error(f"Failed to process {file_path.name}: {e}")
            result.errors += 1
    
    def _resolve_conflict(self, target_path: Path, strategy: ConflictStrategy) -> Path | None:
        """Resolve file name conflict based on strategy."""
        if strategy == ConflictStrategy.SKIP:
            return None
        elif strategy == ConflictStrategy.RENAME:
            return generate_unique_filename(target_path)
        elif strategy == ConflictStrategy.OVERWRITE:
            target_path.unlink(missing_ok=True)
            return target_path
        elif strategy == ConflictStrategy.DELETE:
            return None  # Source will be deleted later
    
    def _log_results(self, result: OrganizationResult, dry_run: bool) -> None:
        """Log organization results."""
        mode = "DRY RUN" if dry_run else "COMPLETE"
        logger.success(
            f"{mode}: {result.organized} organized, "
            f"{result.skipped} skipped, "
            f"{result.conflicts} conflicts, "
            f"{result.errors} errors"
        )
        
        if result.discovered_categories:
            categories = ", ".join(sorted(result.discovered_categories))
            logger.info(f"Categories: {categories}")


class EfficientFileOrganizationOrchestrator:
    """
    Efficient orchestrator with single-pass and batch conflict resolution.
    
    OPTIMIZATIONS:
        - Single pass through files
        - Batch conflict resolution at the end
        - No dry-run needed (single pass only)
        - Interactive conflict resolution prompts
    """
    
    @with_logging
    def organize_files(
        self,
        source_dir: Path,
        *,
        default_strategy: ConflictStrategy = ConflictStrategy.SKIP,
        recursive: bool = False,
        max_files: int = MAX_FILES
    ) -> OrganizationResult:
        """Single-pass organization with batch conflict resolution."""
        # Validate source directory
        source_validation = parse_source_directory_secure(source_dir, max_files)
        if source_validation.is_invalid:
            error_messages = "\n".join([str(e) for e in source_validation.errors])
            raise ValidationError(f"Invalid source directory:\n{error_messages}")
        
        validated_dir = source_validation.value
        if validated_dir is None:
            raise ValidationError("Parsed source directory returned None")
        
        result = OrganizationResult()
        created_categories: Set[str] = set()
        
        # Track conflicts for batch resolution
        conflicts: List[Tuple[Path, Path]] = []  # (source_file, target_path)
        conflict_files: Set[Path] = set()  # Files that have conflicts
        
        # First pass: Organize all non-conflicting files, track conflicts
        all_files = list(self._get_file_iterator(validated_dir, recursive))
        all_files = all_files[:max_files]
        
        if not all_files:
            logger.info("No files to organize")
            return result
        
        logger.info(f"Found {len(all_files)} files to organize")
        
        with tqdm(
            total=len(all_files),
            desc="🏢 Organizing",
            unit="files",
            colour="blue",
            bar_format="{l_bar}{bar:40}{r_bar}",
            ncols=80,
            mininterval=0.1,
        ) as pbar:
            for file_path in all_files:
                try:
                    file_info = gather_file_metadata(file_path)
                    result.discovered_categories.add(file_info.category)
                    
                    category_dir = validated_dir / file_info.category
                    if file_info.category not in created_categories and not category_dir.exists():
                        category_dir.mkdir(exist_ok=True)
                        created_categories.add(file_info.category)
                        result.created_categories_count += 1
                    
                    if file_path.parent == category_dir:
                        result.skipped += 1
                        pbar.update(1)
                        continue
                    
                    target_path = category_dir / file_info.name
                    
                    # Check for conflict
                    if target_path.exists():
                        # Track conflict for batch resolution
                        conflicts.append((file_path, target_path))
                        conflict_files.add(file_path)
                        result.conflicts += 1
                    else:
                        # No conflict - move immediately
                        shutil.move(str(file_path), str(target_path))
                        result.operations.append((file_path, target_path))
                        result.organized += 1
                        
                except ValidationError as e:
                    logger.error(f"Validation failed for {file_path.name}: {e}")
                    result.errors += 1
                except Exception as e:
                    logger.error(f"Failed to process {file_path.name}: {e}")
                    result.errors += 1
                
                pbar.update(1)
        
        # Batch conflict resolution at the END (if any conflicts)
        if conflicts:
            strategy = self._prompt_for_batch_conflict_strategy(len(conflicts), default_strategy)
            
            if strategy is not None and strategy != ConflictStrategy.SKIP:
                resolved_count = self._apply_batch_strategy(
                    conflicts, conflict_files, strategy, result
                )
                typer.echo(f"✅ Resolved {resolved_count} conflicts with '{strategy.value}' strategy.")
        
        logger.success(
            f"COMPLETE: {result.organized} organized, "
            f"{result.skipped} skipped, "
            f"{result.conflicts} conflicts, "
            f"{result.errors} errors"
        )
        
        if result.discovered_categories:
            categories = ", ".join(sorted(result.discovered_categories))
            logger.info(f"Categories: {categories}")
            
        return result
    
    def _get_file_iterator(self, source_dir: Path, recursive: bool) -> Iterator[Path]:
        """Get iterator for files based on recursive flag."""
        if recursive:
            return (f for f in source_dir.rglob("*") if f.is_file())
        else:
            return (f for f in source_dir.iterdir() if f.is_file())
    
    def _prompt_for_batch_conflict_strategy(
        self, 
        conflict_count: int,
        current_strategy: ConflictStrategy
    ) -> ConflictStrategy | None:
        """Prompt user for how to handle ALL conflicts at once."""
        if conflict_count == 0:
            return None
            
        typer.echo(f"\n{'!'*60}")
        typer.echo(f"⚠️  BATCH CONFLICT RESOLUTION")
        typer.echo(f"{'!'*60}")
        typer.echo(f"Found {conflict_count} file conflicts during organization.")
        
        typer.echo(f"\nHow would you like to handle these {conflict_count} conflicts?")
        typer.echo(f"1. Skip all (keep current '{current_strategy.value}' strategy)")
        typer.echo("2. Rename all conflicted files (file.txt → file_1.txt)")
        typer.echo("3. Overwrite all (DANGEROUS - deletes target files)")
        typer.echo("4. Delete all conflicted source files (DANGEROUS)")
        typer.echo("5. Cancel - leave conflicted files as-is")
        
        while True:
            choice = typer.prompt("\nChoose option (1-5)", default="1", show_choices=False).strip()
            
            if choice == "1":
                return current_strategy
            elif choice == "2":
                return ConflictStrategy.RENAME
            elif choice == "3":
                typer.echo("\n" + "!"*50)
                typer.echo("⚠️  CRITICAL WARNING: BATCH OVERWRITE")
                typer.echo("!"*50)
                typer.echo(f"This will PERMANENTLY DELETE {conflict_count} files!")
                if typer.confirm("\nAre you ABSOLUTELY sure?"):
                    return ConflictStrategy.OVERWRITE
                continue
            elif choice == "4":
                typer.echo("\n" + "!"*50)
                typer.echo("⚠️  CRITICAL WARNING: BATCH DELETE")
                typer.echo("!"*50)
                typer.echo(f"This will PERMANENTLY DELETE {conflict_count} source files!")
                if typer.confirm("\nAre you ABSOLUTELY sure?"):
                    return ConflictStrategy.DELETE
                continue
            elif choice == "5":
                return None  # User cancelled conflict resolution
            else:
                typer.echo("Invalid choice. Please enter 1-5.")
    
    def _apply_batch_strategy(
        self,
        conflicts: List[Tuple[Path, Path]],
        conflict_files: Set[Path],
        strategy: ConflictStrategy,
        result: OrganizationResult
    ) -> int:
        """Apply chosen strategy to all conflicts."""
        resolved_count = 0
        
        for file_path, target_path in conflicts:
            try:
                if strategy == ConflictStrategy.RENAME:
                    new_target = generate_unique_filename(target_path)
                    shutil.move(str(file_path), str(new_target))
                    result.operations.append((file_path, new_target))
                    result.organized += 1
                    result.conflicts -= 1
                    resolved_count += 1
                elif strategy == ConflictStrategy.OVERWRITE:
                    target_path.unlink(missing_ok=True)
                    shutil.move(str(file_path), str(target_path))
                    result.operations.append((file_path, target_path))
                    result.organized += 1
                    result.conflicts -= 1
                    resolved_count += 1
                elif strategy == ConflictStrategy.DELETE:
                    file_path.unlink(missing_ok=True)
                    result.conflicts -= 1
                    resolved_count += 1
                # SKIP is handled by doing nothing
            except Exception as e:
                logger.error(f"Failed to resolve conflict for {file_path.name}: {e}")
                result.errors += 1
        
        return resolved_count

# =============================================================================
# CLI INTERFACE - User-facing commands
# =============================================================================

app = typer.Typer(
    help="🏢 Production File Organizer with Backup System",
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]}
)


def _setup_environment() -> None:
    """Setup logging and required directories."""
    setup_logging()
    ensure_directories_exist()


def _handle_validation_result[T](validation: Validated[T], context: str = "") -> T:
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


def prompt_for_conflict_strategy() -> ConflictStrategy:
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
    _setup_environment()
    
    try:
        # ========== SETUP & VALIDATION ==========
        if interactive:
            typer.echo("\n" + "="*50)
            typer.echo("🏢 FILE ORGANIZER - Interactive Mode")
            typer.echo("="*50)
            try:
                conflict_strategy = prompt_for_conflict_strategy()
            except typer.Abort:
                typer.echo("Operation cancelled.")
                sys.exit(0)
        else:
            strategy_validation = parse_conflict_strategy(strategy)
            conflict_strategy = _handle_validation_result(strategy_validation, "Conflict strategy")
        
        # Validate source directory
        source_validation = parse_source_directory_secure(source_dir, max_files)
        validated_source = _handle_validation_result(source_validation, "Source directory")
        
        # ========== WARNINGS FOR DANGEROUS STRATEGIES ==========
        if conflict_strategy == ConflictStrategy.DELETE and not dry_run:
            typer.echo("\n" + "!"*40)
            typer.echo("⚠️  DELETE STRATEGY SELECTED")
            typer.echo("!"*40)
            typer.echo("Conflicted source files will be PERMANENTLY DELETED!")
            
            if not typer.confirm("\nAre you sure you want to delete files?"):
                raise typer.Abort("Delete strategy cancelled by user.")
            
            if not backup:
                typer.echo("\n💡 STRONGLY RECOMMENDED: Backup before deleting files")
                if typer.confirm("Create backup before proceeding?"):
                    backup = True
        
        if conflict_strategy == ConflictStrategy.OVERWRITE and not dry_run:
            typer.echo("\n" + "!"*50)
            typer.echo("⚠️  WARNING: OVERWRITE STRATEGY SELECTED")
            typer.echo("!"*50)
            typer.echo("This will PERMANENTLY DELETE duplicate files!")
            
            if not typer.confirm("\nAre you ABSOLUTELY sure you want to continue?"):
                raise typer.Abort("Overwrite strategy cancelled by user.")
            
            if not backup:
                typer.echo("\n💡 RECOMMENDATION: Consider creating a backup")
                if typer.confirm("Create backup before proceeding?"):
                    backup = True
        
        # ========== BACKUP CREATION ==========
        backup_path = None
        if backup and not dry_run:
            typer.echo("\n💾 Creating backup...")
            backup_orchestrator = BackupOrchestrator()
            backup_path = backup_orchestrator.create_backup(
                validated_source, 
                compress=True
            )
            if backup_path:
                typer.echo(f"✅ Backup created: {backup_path}")
            else:
                typer.echo("⚠️  Backup creation failed")
                if not typer.confirm("Continue without backup?"):
                    sys.exit(1)
        
        # ========== EXECUTION CONFIRMATION ==========
        if not dry_run:
            # Show execution summary
            typer.echo("\n" + "="*50)
            typer.echo("🚀 EXECUTION SUMMARY")
            typer.echo("="*50)
            typer.echo(f"Source: {validated_source}")
            typer.echo(f"Strategy: {conflict_strategy.value}")
            typer.echo(f"Mode: {'Recursive' if recursive else 'Current folder only'}")
            typer.echo(f"Max files: {max_files}")
            typer.echo(f"Backup: {'✅ Yes' if backup else '❌ No'}")
            
            if not typer.confirm("\nProceed with file organization?"):
                raise typer.Abort("Operation cancelled by user.")
        
        # ========== EXECUTION ==========
        if dry_run:
            # ===== DRY RUN MODE =====
            typer.echo("\n🧪 DRY RUN MODE")
            typer.echo("No files will be modified.")
            organizer = FileOrganizationOrchestrator()
            result = organizer.organize_files(
                source_dir=validated_source,
                conflict_strategy=conflict_strategy,
                dry_run=True,
                recursive=recursive,
                max_files=max_files
            )
            
            completion_msg = "🧪 DRY RUN COMPLETE"
            completion_details = "No changes were made to your files."
            
        else:
            # ===== EFFICIENT EXECUTION =====
            typer.echo("\n" + "="*50)
            typer.echo("🚀 EXECUTING FILE ORGANIZATION")
            typer.echo("="*50)
            typer.echo("• Single-pass efficient mode")
            typer.echo("• Batch conflict resolution")
            
            organizer = EfficientFileOrganizationOrchestrator()
            result = organizer.organize_files(
                source_dir=validated_source,
                default_strategy=conflict_strategy,
                recursive=recursive,
                max_files=max_files
            )
            
            completion_msg = "✅ ORGANIZATION COMPLETE"
            completion_details = "Files have been organized successfully."
        
        # ========== RESULTS DISPLAY ==========
        typer.echo(f"\n📊 RESULTS:")
        typer.echo(f"  Organized: {result.organized}")
        typer.echo(f"  Skipped: {result.skipped}")
        typer.echo(f"  Conflicts: {result.conflicts}")
        typer.echo(f"  Errors: {result.errors}")
        
        if result.discovered_categories:
            categories = ", ".join(sorted(result.discovered_categories))
            typer.echo(f"  Categories: {categories}")
        
        # Success message for actual execution
        if result.organized > 0 and not dry_run:
            typer.echo(f"\n✅ Successfully organized {result.organized} files!")
            if backup_path:
                typer.echo(f"💾 Backup available: {backup_path}")
        
        # Conflict explanation
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
        
        # Final completion message
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
    _setup_environment()
    
    try:
        backup_orchestrator = BackupOrchestrator(backup_dir)
        
        # List backups if requested
        if list_backups:
            backups = backup_orchestrator.list_backups()
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
        
        # Restore backup if requested
        if restore:
            if not restore.exists():
                typer.echo(f"❌ Backup not found: {restore}")
                sys.exit(1)
            
            typer.echo(f"\n🔄 Restoring backup: {restore.name}")
            typer.echo(f"   To: {restore_to}")
            
            if not typer.confirm("\nProceed with restore?"):
                raise typer.Abort("Restore cancelled by user.")
            
            success = backup_orchestrator.restore_backup(restore, restore_to)
            if success:
                typer.echo(f"✅ Backup restored successfully to {restore_to}")
            else:
                typer.echo(f"❌ Backup restore failed")
                sys.exit(1)
            return
        
        # Create backup
        typer.echo(f"\n💾 Creating backup of: {source_dir}")
        typer.echo(f"   To: {backup_dir}")
        typer.echo(f"   Compression: {compress} ({compression_format})")
        
        if not typer.confirm("\nProceed with backup?"):
            raise typer.Abort("Backup cancelled by user.")
        
        backup_path = backup_orchestrator.create_backup(
            source_dir,
            compress=compress,
            compression_format=compression_format
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
    _setup_environment()
    
    try:
        source_validation = parse_source_directory_secure(source_dir, max_files)
        validated_source = _handle_validation_result(source_validation, "Source directory")
        
        categories = set()
        file_count = 0
        category_counts = {}
        
        for item in validated_source.iterdir():
            if item.is_file():
                file_count += 1
                try:
                    category = extract_file_category(item)
                    categories.add(category)
                    category_counts[category] = category_counts.get(category, 0) + 1
                except ValidationError:
                    continue
        
        typer.echo(f"\n📊 Analysis of: {validated_source}")
        typer.echo(f"  Total files: {file_count:,}")
        typer.echo(f"  Unique categories: {len(categories)}")
        
        if categories:
            typer.echo("\n  Categories that would be created:")
            for category in sorted(categories):
                count = category_counts.get(category, 0)
                percentage = (count / file_count * 100) if file_count > 0 else 0
                typer.echo(f"    • {category}/ - {count:,} files ({percentage:.1f}%)")
            
    except Exception as e:
        typer.echo(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    app()