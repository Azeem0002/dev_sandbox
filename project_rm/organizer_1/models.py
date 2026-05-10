from __future__ import annotations
"""Core data models and shared config for organizer.

This module defines the stable domain vocabulary used across validation,
application, and service layers.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

from platformdirs import PlatformDirs


class ValidationError(Exception):
    """Business-rule validation failure."""


@dataclass
class Validated[T]:
    """Validation result object that carries either a value or accumulated errors."""
    value: T | None = None
    errors: list[ValidationError] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """Return whether valid."""
        return self.value is not None and not self.errors

    @property
    def is_invalid(self) -> bool:
        """Return whether invalid."""
        return not self.is_valid

    def get_or_raise(self) -> T:
        """Return or raise."""
        if self.is_invalid:
            error_msg = str(self.errors[0]) if self.errors else "Invalid value"
            raise ValidationError(error_msg)

        assert self.value is not None, "Invariant broken: value must exist when valid"
        return self.value

    def map[U](self, op) -> Validated[U]:
        """Map."""
        if self.is_invalid:
            return Validated(None, self.errors.copy())

        assert self.value is not None, "Invariant broken: value must exist when valid"
        return Validated(op(self.value), self.errors.copy())

    def bind[U](self, op) -> Validated[U]:
        """Bind."""
        if self.is_invalid:
            return Validated(None, self.errors.copy())

        assert self.value is not None, "Invariant broken: value must exist when valid"
        result = op(self.value)
        return Validated(result.value, self.errors + result.errors.copy())

    def __and__[U](self, other: Validated[U]) -> Validated[tuple[T, U]]:
        """And."""
        if self.is_valid and other.is_valid:
            assert self.value is not None
            assert other.value is not None
            return Validated((self.value, other.value), self.errors + other.errors.copy())

        return Validated(None, self.errors + other.errors.copy())


@dataclass(frozen=True)
class AppConfig:
    """Static app-level configuration values shared by organizer modules."""
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
    SKIP = "skip"
    RENAME = "rename"
    OVERWRITE = "overwrite"
    DELETE = "delete"


@dataclass
class FileInfo:
    path: Path
    name: str
    stem: str
    suffix: str
    category: str
    size: int = 0
    permission: int | None = None
    created: datetime | None = None
    modified: datetime | None = None


@dataclass
class OrganizationResult:
    organized: int = 0
    skipped: int = 0
    conflicts: int = 0
    errors: int = 0
    created_categories_count: int = 0
    operations: list[tuple[Path, Path]] = field(default_factory=list)
    discovered_categories: set[str] = field(default_factory=set)


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
        """Categories."""
        return sorted(self.category_counts)


@dataclass
class OrganizeOperationState:
    source_dir: str
    conflict_strategy: str
    recursive: bool
    max_files: int
    started_at: str
    completed_paths: list[str] = field(default_factory=list)
