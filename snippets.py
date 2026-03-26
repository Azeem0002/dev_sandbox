def copy_directory_with_progress_secure(src_dir: Path, dst_dir: Path) -> int:
    """
    Pure streaming copy with honest "at least X files" progress.
    """
    
    # =========================================================================
    # VALIDATION
    # =========================================================================
    
    if parse_backup_source(src_dir).is_invalid:
        raise ValidationError("Invalid source")
    
    if parse_backup_destination(dst_dir).is_invalid:
        raise ValidationError("Invalid destination")
    
    # =========================================================================
    # ESTIMATION (Nested function)
    # =========================================================================
    
    def quick_sample(directory: Path, limit: int = 1000) -> int:
        """Return number of files found up to limit."""
        count = 0
        for item in directory.rglob("*"):
            if item.is_file():
                count += 1
                if count >= limit:
                    break
        return count
    
    is_terminal = sys.stderr.isatty()
    min_files = quick_sample(src_dir) if is_terminal else 0
    
    if min_files == 0 and is_terminal:
        logger.info("No files found")
        return 0
    
    if is_terminal:
        logger.info(f"Found at least {min_files:,} files")
    
    # =========================================================================
    # STREAMING COPY
    # =========================================================================
    
    copied = 0
    failed = 0
    bytes_total = 0
    start = datetime.now()
    items = 0
    
    SAFETY_LIMIT = 1_000_000
    
    # Check for tqdm
    has_tqdm = False
    if is_terminal:
        try:
            from tqdm import tqdm
            has_tqdm = True
        except ImportError:
            pass
    
    try:
        if has_tqdm and min_files > 0:
            with tqdm(total=min_files, desc="📁 Copying", unit="files") as pbar:
                for item in src_dir.rglob("*"):
                    items += 1
                    if items > SAFETY_LIMIT:
                        raise ValidationError(f"Too many items: {items:,}")
                    
                    if not item.is_file():
                        continue
                    
                    try:
                        size = _copy_single_file_secure(item, src_dir, dst_dir)
                        copied += 1
                        bytes_total += size
                        pbar.update(1)
                        
                        if copied % 100 == 0:
                            elapsed = (datetime.now() - start).total_seconds()
                            rate = copied / elapsed if elapsed > 0 else 0
                            mb = bytes_total / (1024 * 1024)
                            pbar.set_description(f"📁 {copied:,} | {mb:.0f} MB | {rate:.0f}/sec")
                            
                    except Exception as e:
                        logger.warning(f"Failed: {item.name}: {e}")
                        failed += 1
        else:
            # Simple logging mode
            for item in src_dir.rglob("*"):
                items += 1
                if items > SAFETY_LIMIT:
                    raise ValidationError(f"Too many items: {items:,}")
                
                if not item.is_file():
                    continue
                
                try:
                    size = _copy_single_file_secure(item, src_dir, dst_dir)
                    copied += 1
                    bytes_total += size
                    
                    if is_terminal and copied % 100 == 0:
                        elapsed = (datetime.now() - start).total_seconds()
                        rate = copied / elapsed if elapsed > 0 else 0
                        mb = bytes_total / (1024 * 1024)
                        print(f"\r📁 {copied:,} / at least {min_files:,} | {mb:.0f} MB | {rate:.0f}/sec", 
                              end="", flush=True)
                        
                except Exception as e:
                    logger.warning(f"Failed: {item.name}: {e}")
                    failed += 1
            
            if is_terminal and copied > 0:
                print()
        
        if copied == 0 and failed == 0:
            logger.info("No files found")
            return 0
            
    except KeyboardInterrupt:
        elapsed = (datetime.now() - start).total_seconds()
        logger.warning(f"\n⚠️ Stopped: {copied:,} copied, {failed:,} failed")
        raise
    
    elapsed = (datetime.now() - start).total_seconds()
    gb = bytes_total / (1024 * 1024 * 1024)
    rate = copied / elapsed if elapsed > 0 else 0
    
    logger.success(f"\n✅ Done: {copied:,} files, {gb:.2f} GB, {rate:.1f}/sec")
    
    return copied