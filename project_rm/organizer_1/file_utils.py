"""Reusable file-oriented helpers for organizer.

These are lower-level primitives such as category detection, metadata gathering,
and unique target-name generation.
"""

import re
from datetime import datetime
from pathlib import Path

try:
    from .models import FileInfo, ValidationError
except ImportError:
    from models import FileInfo, ValidationError


# REUSABLE: extension-to-category mapping is a useful file-organizer primitive.
def extract_file_category(
    file_path: Path,
    *,
    custom_mapping: dict[str, str] | None = None,
) -> str:
    """Extract file category."""
    if custom_mapping is None:
        custom_mapping = {}

    if file_path.name.startswith("."):
        return "hidden"

    file_suffixes = file_path.suffixes
    if not file_suffixes:
        return "no_extension"

    compound_extension = "".join(file_suffixes).lower()
    last_extension = file_suffixes[-1].lower() if file_suffixes else ""

    if compound_extension in custom_mapping:
        return custom_mapping[compound_extension]
    if last_extension in custom_mapping:
        return custom_mapping[last_extension]

    category_map = {
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
        ".pdf": "documents",
        ".doc": "documents", ".docx": "documents",
        ".txt": "documents", ".rtf": "documents",
        ".odt": "documents", ".md": "documents",
        ".pages": "documents",
        ".xls": "spreadsheets", ".xlsx": "spreadsheets",
        ".ods": "spreadsheets", ".csv": "spreadsheets",
        ".ppt": "presentations", ".pptx": "presentations",
        ".odp": "presentations", ".key": "presentations",
        ".zip": "archives", ".tar": "archives",
        ".rar": "archives", ".7z": "archives",
        ".bz2": "archives", ".gz": "archives",
        ".tar.gz": "archives", ".tar.bz2": "archives",
        ".tar.xz": "archives", ".tgz": "archives",
        ".py": "code", ".js": "code", ".java": "code",
        ".cpp": "code", ".c": "code", ".html": "code",
        ".css": "code", ".json": "code", ".xml": "code",
        ".yaml": "code", ".yml": "code", ".toml": "code",
        ".ini": "code", ".cfg": "code", ".conf": "code",
        ".exe": "executables", ".msi": "executables",
        ".app": "executables", ".sh": "executables",
        ".bat": "executables", ".cmd": "executables",
    }

    if compound_extension in category_map:
        return category_map[compound_extension]
    if last_extension in category_map:
        return category_map[last_extension]

    base_category = "".join(s.lstrip(".") for s in file_suffixes) if len(file_suffixes) > 1 else last_extension.lstrip(".")
    category = re.sub(r"[^\w\-]", "_", base_category)
    if not category or category.isspace():
        return "misc"
    return category.strip()


# REUSABLE: metadata gathering is a cross-project helper for file workflows.
def gather_file_metadata(file_path: Path) -> FileInfo:
    """Gather file metadata."""
    if not file_path.is_file():
        raise ValidationError(f"Not a file: {file_path}")

    try:
        stat = file_path.stat()
    except (PermissionError, OSError) as error:
        raise ValidationError(f"Cannot read file metadata: {error}") from error

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


# REUSABLE: collision-safe filename generation is broadly reusable.
def generate_unique_filename(target_path: Path, max_attempts: int = 1000) -> Path:
    """Generate unique filename."""
    counter = 1
    parent = target_path.parent
    stem = target_path.stem
    suffix = target_path.suffix

    while counter <= max_attempts:
        new_name = parent / f"{stem}_{counter}{suffix}"
        if not new_name.exists():
            return new_name
        counter += 1

    raise RuntimeError(f"Could not generate unique name after {max_attempts} attempts")
