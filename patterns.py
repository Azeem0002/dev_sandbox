from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Set, Tuple, Optional, Callable
from enum import Enum
from datetime import datetime
import re
import sys
import shutil

import typer
from loguru import logger





# =============================================================================
# VALIDATION PATTERN
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
# FILEINFO METADATA PATTERN
# =============================================================================

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

        # Documents
        ".pdf": "documents",
        ".doc": "documents", ".docx": "documents",
        
        # Archives - singles and compounds
        ".zip": "archives", ".tar": "archives",

        # Compound archives
        ".tar.gz": "archives", ".tar.bz2": "archives",
        
        # Code
        ".py": "code", ".js": "code", ".java": "code",
        
        # Executables
        ".exe": "executables", ".msi": "executables",
        
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

# =============================================================================
# Logging Pattern
# =============================================================================

BACKUP_DIR: Path = Path.home() / ".file_organizer" / "backups"
LOG_DIR: Path = Path.home() / ".file_organizer" / "logs"

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


# =============================================================================
# DRY RUN PATTERN
# =============================================================================

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