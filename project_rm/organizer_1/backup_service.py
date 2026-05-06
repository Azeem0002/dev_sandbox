import shutil
import sys
import tarfile
import time
import zipfile
from datetime import datetime
from functools import wraps
from pathlib import Path

from loguru import logger
from tqdm import tqdm

try:
    from .file_utils import generate_unique_filename
    from .models import APP_CONFIG, BackupCommandInput, ValidationError, Validated
    from .validation import parse_backup_destination, parse_backup_source
except ImportError:
    from file_utils import generate_unique_filename
    from models import APP_CONFIG, BackupCommandInput, ValidationError, Validated
    from validation import parse_backup_destination, parse_backup_source


def _get_validated_value[T](validation: Validated[T], context: str = "") -> T:
    if validation.is_invalid:
        error_text = ", ".join(str(error) for error in validation.errors) or "invalid value"
        raise ValidationError(f"{context or 'Validation'} failed: {error_text}")

    value = validation.value
    if value is None:
        raise ValidationError(f"{context or 'Value'} unexpectedly None after validation")
    return value


def _validate_paths(src_dir: Path, dst_dir: Path) -> None:
    """Guard against obviously dangerous or invalid backup path combinations."""
    source_validation = parse_backup_source(src_dir)
    if source_validation.is_invalid:
        errors = "\n".join(str(error) for error in source_validation.errors)
        raise ValidationError(f"Invalid source directory:\n{errors}")

    dest_validation = parse_backup_destination(dst_dir)
    if dest_validation.is_invalid:
        errors = "\n".join(str(error) for error in dest_validation.errors)
        raise ValidationError(f"Invalid destination directory:\n{errors}")

    logger.debug(f"Security validation passed: {src_dir} -> {dst_dir}")


# REUSABLE: secure copy with verification and cleanup is broadly reusable.
def copy_single_file_secure(src_file: Path, src_root: Path, dst_root: Path) -> int:
    """Copy one file while preserving a safe relative path under the destination root."""
    try:
        relative_path = src_file.relative_to(src_root)
    except ValueError as error:
        raise ValidationError(
            f"Security violation: File {src_file} is not under source root {src_root}"
        ) from error

    dest_file = dst_root / relative_path
    dest_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        file_size = src_file.stat().st_size
    except OSError as error:
        raise PermissionError(f"Cannot read source file {src_file.name}: {error}") from error

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            shutil.copy2(src_file, dest_file)
            if not dest_file.exists():
                raise OSError("Target file not created after copy operation")
            copied_size = dest_file.stat().st_size
            if copied_size != file_size:
                dest_file.unlink(missing_ok=True)
                raise OSError(f"Copy incomplete: {copied_size:,} of {file_size:,} bytes transferred")
            return file_size
        except (OSError, IOError, PermissionError) as error:
            last_error = error
            dest_file.unlink(missing_ok=True)
            if attempt < 2:
                sleep_time = 0.1 * ((attempt + 1) ** 2)
                logger.debug(f"Retry {attempt + 1}/3 for {src_file.name}: {error}, waiting {sleep_time:.1f}s")
                time.sleep(sleep_time)
            else:
                logger.debug(f"Final copy attempt failed for {src_file.name}: {error}")

    raise last_error or OSError(f"Unknown error copying {src_file.name}")


def copy_directory_with_progress_secure(src_dir: Path, dst_dir: Path) -> int:
    """
    Flow:
        create_backup | restore_backup -> copy_directory_with_progress_secure
        copy_directory_with_progress_secure
            -> _validate_paths
            -> estimate_files
            -> _copy_one_file
            -> report_copy_results
    """
    _validate_paths(src_dir, dst_dir)
    is_terminal = sys.stderr.isatty()
    min_files = estimate_files(src_dir) if is_terminal else 0

    if min_files == 0 and is_terminal:
        logger.info("No files found")
        return 0
    if is_terminal:
        logger.info(f"Found at least {min_files:,} files")

    logger.info(f"Starting streaming copy from {src_dir} to {dst_dir}")
    start_time = datetime.now()
    stats = {"total_items": 0, "processed": 0, "copied": 0, "skipped": 0, "bytes": 0}

    try:
        if is_terminal and min_files > 0:
            with tqdm(total=min_files, desc="Copying", unit="files") as progress:
                for item in src_dir.rglob("*"):
                    stats["total_items"] += 1
                    check_copy_safety(stats["total_items"], start_time)
                    if not item.is_file():
                        continue
                    _copy_one_file(item, src_dir, dst_dir, stats)
                    progress.update(1)
        else:
            for item in src_dir.rglob("*"):
                stats["total_items"] += 1
                check_copy_safety(stats["total_items"], start_time)
                if not item.is_file():
                    continue
                _copy_one_file(item, src_dir, dst_dir, stats)
    except KeyboardInterrupt:
        _handle_interrupt(start_time, stats)
        raise
    except Exception as error:
        _handle_error(start_time, error)
        raise

    if stats["processed"] == 0:
        logger.info(f"No files found in {src_dir}")
        return 0

    report_copy_results(start_time, stats, src_dir, dst_dir)
    return stats["copied"]


# REUSABLE: bounded estimation is a useful fast preflight pattern.
def estimate_files(directory: Path, limit: int = 1000) -> int:
    """Cheap preflight count used for progress display and safety checks."""
    count = 0
    for item in directory.rglob("*"):
        if item.is_file():
            count += 1
            if count >= limit:
                break
    return count


def check_copy_safety(total_items: int, start: datetime) -> None:
    """Abort obviously suspicious copy sizes before the run becomes dangerous."""
    safety_limit = 1_000_000
    if total_items <= safety_limit:
        return
    elapsed = (datetime.now() - start).total_seconds()
    raise ValidationError(
        f"Safety limit exceeded: {total_items:,} > {safety_limit:,} items.\n"
        f"Processed for {elapsed:.1f}s before hitting limit."
    )


def _copy_one_file(item: Path, src_dir: Path, dst_dir: Path, stats: dict[str, int]) -> None:
    try:
        bytes_copied = copy_single_file_secure(item, src_dir, dst_dir)
        stats["copied"] += 1
        stats["bytes"] += bytes_copied
    except Exception as error:
        logger.warning(f"Failed to copy {item.name}: {error}")
        stats["skipped"] += 1
    finally:
        stats["processed"] += 1


def _handle_interrupt(start: datetime, stats: dict[str, int]) -> None:
    elapsed = (datetime.now() - start).total_seconds()
    logger.warning(
        f"\nCopy interrupted after {elapsed:.1f}s\n"
        f"Copied: {stats['copied']:,} files\n"
        f"Failed: {stats['skipped']:,} files"
    )


def _handle_error(start: datetime, error: Exception) -> None:
    elapsed = (datetime.now() - start).total_seconds()
    logger.error(f"Copy failed after {elapsed:.1f}s: {error}")


def report_copy_results(start: datetime, stats: dict[str, int], src_dir: Path, dst_dir: Path) -> None:
    elapsed = (datetime.now() - start).total_seconds()
    gb = stats["bytes"] / (1024 * 1024 * 1024)
    rate = stats["copied"] / elapsed if elapsed > 0 else 0
    byte_rate = stats["bytes"] / elapsed if elapsed > 0 else 0
    logger.success(
        f"\nCOPY COMPLETE\n"
        f"Files copied: {stats['copied']:,}\n"
        f"Files failed: {stats['skipped']:,}\n"
        f"Total data: {gb:.2f} GB\n"
        f"Copy time: {elapsed:.1f}s\n"
        f"Speed: {rate:.1f} files/sec, {byte_rate/1024/1024:.1f} MB/sec"
    )
    logger.debug(
        f"SECURITY AUDIT LOG\n"
        f"Source: {src_dir}\nDestination: {dst_dir}\n"
        f"Items scanned: {stats['total_items']:,}\n"
        f"Files copied: {stats['copied']:,}\nFiles failed: {stats['skipped']:,}"
    )


# REUSABLE: small logging decorator pattern worth learning once.
def with_logging(func):
    """Decorator that logs start/success/failure around one backup step."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        logger.debug(f"Starting {func.__name__}")
        try:
            result = func(*args, **kwargs)
            logger.debug(f"Completed {func.__name__}")
            return result
        except Exception as error:
            logger.error(f"{func.__name__} failed: {error}")
            raise
    return wrapper


# REUSABLE: lightweight retry decorator pattern worth learning once.
def with_retry(max_attempts: int = 3):
    """Decorator factory for retrying transient backup failures."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as error:
                    last_exception = error
                    if attempt < max_attempts - 1:
                        logger.warning(f"Attempt {attempt + 1} failed, retrying...")
            raise last_exception or RuntimeError("All retry attempts failed")
        return wrapper
    return decorator


class DiskSpaceManager:
    BUFFER_PERCENT = 20
    MIN_FREE_PERCENT = 10

    @classmethod
    def check_space_for_backup(
        cls,
        source_dir: Path,
        destination_dir: Path,
        estimate_only: bool = False,
    ) -> tuple[bool, str | None, int | None]:
        try:
            source_size = (
                cls._estimate_source_size_fast(source_dir)
                if estimate_only
                else cls._calculate_source_size_accurate(source_dir)
            )
            if source_size == 0:
                return True, "No files to backup", 0

            try:
                dst_usage = shutil.disk_usage(destination_dir)
            except OSError as error:
                logger.warning(f"Cannot get disk usage for {destination_dir}: {error}")
                return True, None, source_size

            required_space = source_size * (1 + cls.BUFFER_PERCENT / 100)
            if dst_usage.free < required_space:
                needed_gb = required_space / (1024**3)
                free_gb = dst_usage.free / (1024**3)
                total_gb = dst_usage.total / (1024**3)
                return False, (
                    f"INSUFFICIENT DISK SPACE\n"
                    f"Source size: {source_size/1024**3:.1f} GB\n"
                    f"Required (with {cls.BUFFER_PERCENT}% buffer): {needed_gb:.1f} GB\n"
                    f"Available: {free_gb:.1f} GB\n"
                    f"Drive capacity: {total_gb:.1f} GB\n"
                    f"Short by: {needed_gb - free_gb:.1f} GB"
                ), source_size

            remaining_after_backup = dst_usage.free - source_size
            min_required_free = dst_usage.total * (cls.MIN_FREE_PERCENT / 100)
            if remaining_after_backup < min_required_free:
                return True, (
                    f"WARNING: Backup will leave only {remaining_after_backup/1024**3:.1f} GB free\n"
                    f"Recommended minimum: {min_required_free/1024**3:.1f} GB"
                ), source_size

            return True, None, source_size
        except Exception as error:
            logger.error(f"Disk space check failed: {error}")
            return True, None, None

    @staticmethod
    def _estimate_source_size_fast(source_dir: Path) -> int:
        total = 0
        sample_count = 0
        for item in source_dir.rglob("*"):
            if item.is_file() and sample_count < 100:
                try:
                    total += item.stat().st_size
                    sample_count += 1
                except OSError:
                    continue
        if sample_count == 0:
            return 0
        avg_file_size = total / sample_count
        total_files = sum(1 for item in source_dir.rglob("*") if item.is_file())
        return int(avg_file_size * total_files)

    @staticmethod
    def _calculate_source_size_accurate(source_dir: Path) -> int:
        total = 0
        file_count = 0
        for item in source_dir.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                    file_count += 1
                    if file_count > 100000:
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
        next_file_size: int,
    ) -> tuple[bool, str | None]:
        del copied_so_far
        try:
            dst_usage = shutil.disk_usage(destination_dir)
            if dst_usage.free < next_file_size:
                return False, (
                    f"Disk full! Cannot copy {next_file_size/1024**2:.1f} MB file.\n"
                    f"Only {dst_usage.free/1024**2:.1f} MB free remaining."
                )
            if dst_usage.free < dst_usage.total * 0.05:
                return True, (
                    f"Low disk space: {dst_usage.free/1024**3:.1f} GB remaining "
                    f"({dst_usage.free/dst_usage.total*100:.0f}%)"
                )
            return True, None
        except OSError:
            return True, None


MAX_BACKUP_FILES = 1_000_000


def _copy_backup_directory_with_space_monitoring(src_dir: Path, dst_dir: Path) -> int:
    dest_validation = parse_backup_destination(dst_dir)
    if dest_validation.is_invalid:
        errors = "\n".join(str(error) for error in dest_validation.errors)
        raise ValidationError(f"Invalid backup destination:\n{errors}")

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
            bytes_copied = copy_single_file_secure(file_path, src_dir, dst_dir)
        except Exception as error:
            logger.warning(f"Failed to copy {file_path.name}: {error}")
            continue

        copied_files += 1
        copied_bytes += bytes_copied

    return copied_files


def compress_to_zip(source_dir: Path, archive_path: Path) -> bool:
    try:
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for file_path in source_dir.rglob("*"):
                if file_path.is_file():
                    zip_file.write(file_path, file_path.relative_to(source_dir))
        return True
    except Exception as error:
        logger.error(f"ZIP compression failed: {error}")
        if archive_path.exists():
            archive_path.unlink(missing_ok=True)
        return False


def compress_to_tar_gz(source_dir: Path, archive_path: Path) -> bool:
    try:
        with tarfile.open(archive_path, "w:gz") as tar_file:
            tar_file.add(source_dir, arcname=source_dir.name)
        return True
    except Exception as error:
        logger.error(f"TAR.GZ compression failed: {error}")
        if archive_path.exists():
            archive_path.unlink(missing_ok=True)
        return False


def _compress_backup_directory(backup_dir: Path, compression_format: str) -> Path | None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        if compression_format == "zip":
            archive_path = generate_unique_filename(backup_dir.parent / f"{backup_dir.name}_{timestamp}.zip")
            return archive_path if compress_to_zip(backup_dir, archive_path) else None
        if compression_format == "tar.gz":
            archive_path = generate_unique_filename(backup_dir.parent / f"{backup_dir.name}_{timestamp}.tar.gz")
            return archive_path if compress_to_tar_gz(backup_dir, archive_path) else None
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
    """
    Flow:
        backup -> create_backup
        create_backup
            -> parse_backup_source
            -> DiskSpaceManager.check_space_for_backup
            -> _copy_backup_directory_with_space_monitoring
            -> _compress_backup_directory
    """
    logger.info(f"Starting backup of {input_data.source_dir}")
    source_validation = parse_backup_source(input_data.source_dir)
    if source_validation.is_invalid:
        errors = "\n".join(str(error) for error in source_validation.errors)
        raise ValidationError(f"Invalid backup source:\n{errors}")

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


def get_backups(backup_dir: Path) -> list[Path]:
    """
    Flow:
        backup --list -> get_backups
        get_backups
            -> Path.iterdir
            -> _backup_modified_time
    """
    backups: list[Path] = []
    if backup_dir.exists():
        for item in backup_dir.iterdir():
            if item.name.startswith("backup_") or item.suffix in {".zip", ".tar.gz"}:
                backups.append(item)
    backups.sort(key=_backup_modified_time, reverse=True)
    return backups


def restore_backup(backup_path: Path, restore_dir: Path, backup_dir: Path) -> bool:
    """
    Flow:
        backup --restore -> restore_backup
        restore_backup
            -> parse_backup_destination
            -> DiskSpaceManager.check_space_for_backup
            -> _extract_* | _copy_backup_directory_with_space_monitoring
    """
    logger.info(f"Restoring backup {backup_path} to {restore_dir}")
    del backup_dir

    try:
        dest_validation = parse_backup_destination(restore_dir)
        if dest_validation.is_invalid:
            errors = "\n".join(str(error) for error in dest_validation.errors)
            raise ValidationError(f"Invalid restore directory:\n{errors}")

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
def _backup_modified_time(path: Path) -> float:
    return path.stat().st_mtime
