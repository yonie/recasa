"""File scanner service - discovers and indexes photos from the watch directory.

Smart rescan behavior:
- New files: enter pipeline at DISCOVERY (full processing)
- Existing fully-processed files: skipped entirely
- Existing partially-processed files: enter at first incomplete stage
- Removed files: deleted from DB during cleanup pass

The database is the source of truth for processing state, not in-memory tracking.

Directory fingerprinting for fast rescans:
- On first scan, compute a fingerprint (file_count, total_size, max_mtime) for each directory
- Store fingerprints in memory (lost on app restart)
- On subsequent scans, skip directories with unchanged fingerprints
- This dramatically reduces filesystem I/O for repeated rescans
"""

import asyncio
import hashlib
import logging
import mimetypes
import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import settings
from backend.app.database import async_session
from backend.app.models import Photo, PhotoPath

logger = logging.getLogger(__name__)

# Buffer size for SHA-256 hashing (64KB)
HASH_BUFFER_SIZE = 65536

# In-memory cache of directory fingerprints for fast rescans.
# Persists only within app session - lost on restart.
# Format: {directory_path: (file_count, total_size, max_mtime)}
_directory_cache: dict[str, tuple[int, int, float]] = {}


def clear_directory_cache():
    """Clear the directory fingerprint cache. Use before a full rescan."""
    global _directory_cache
    _directory_cache = {}
    logger.info("Directory fingerprint cache cleared")


def _get_directory_fingerprint(dir_path: Path) -> tuple[int, int, float]:
    """Compute a lightweight fingerprint for a directory.

    Returns (file_count, total_size, max_mtime) for supported photo files.
    This is fast - just iterdir() + stat() on each file in the directory.

    The fingerprint detects:
    - New files (count increases)
    - Deleted files (count decreases)
    - Modified files (size or mtime changes)

    It does NOT detect:
    - Renamed files within same directory (count/size/mtime unchanged)
    """
    count = 0
    total_size = 0
    max_mtime = 0.0
    try:
        for entry in dir_path.iterdir():
            if entry.is_file() and is_supported_photo(entry):
                try:
                    stat = entry.stat()
                    count += 1
                    total_size += stat.st_size
                    max_mtime = max(max_mtime, stat.st_mtime)
                except OSError:
                    pass
    except PermissionError:
        pass
    return (count, total_size, max_mtime)


def compute_file_hash(filepath: Path) -> str:
    """Compute SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            data = f.read(HASH_BUFFER_SIZE)
            if not data:
                break
            sha256.update(data)
    return sha256.hexdigest()


def is_supported_photo(filepath: Path) -> bool:
    """Check if a file is a supported photo format."""
    return filepath.suffix.lower() in settings.photo_extensions


def find_live_photo_video(photo_path: Path) -> Path | None:
    """Find an associated Live Photo video (MOV) for a HEIC/JPEG file."""
    # Apple Live Photos: same name, .MOV extension
    for ext in [".mov", ".MOV"]:
        video_path = photo_path.with_suffix(ext)
        if video_path.exists():
            return video_path
    return None


def detect_google_motion_photo(filepath: Path) -> bool:
    """Check if a JPEG contains embedded Google Motion Photo data.

    Google Motion Photos embed MP4 data at the end of the JPEG file,
    typically after a specific marker.
    """
    if filepath.suffix.lower() not in {".jpg", ".jpeg"}:
        return False

    try:
        with open(filepath, "rb") as f:
            # Read last portion of file to check for MP4 signature
            f.seek(0, 2)  # seek to end
            file_size = f.tell()
            if file_size < 1024:
                return False

            # Look for the ftypmp4 or ftypisom marker in last portion
            search_size = min(file_size, 4 * 1024 * 1024)  # search last 4MB
            f.seek(file_size - search_size)
            data = f.read(search_size)

            return b"ftypmp4" in data or b"ftypisom" in data or b"MotionPhoto" in data
    except OSError:
        return False


def _needs_pipeline_processing(photo: Photo) -> bool:
    """Check if a photo still needs any pipeline processing.

    Returns True if any processing stage has not been completed yet.
    """
    return not all([
        photo.exif_extracted,
        photo.thumbnail_generated,
        photo.perceptual_hashed,
        photo.faces_detected,
        photo.ollama_captioned,
    ])


def _get_pipeline_entry_point(photo: Photo) -> str | None:
    """Determine which pipeline stage a photo should enter.

    Returns the queue name for the first incomplete stage, or None if fully processed.
    Pipeline order: DISCOVERY → EXIF → GEOCODING → THUMBNAILS → MOTION_PHOTOS → HASHING → FACES → CAPTIONING → EVENTS
    """
    if not photo.exif_extracted:
        return "exif"
    if not photo.thumbnail_generated:
        return "thumbnails"
    if not photo.perceptual_hashed:
        return "hashing"
    if not photo.faces_detected:
        return "faces"
    if not photo.ollama_captioned:
        return "captioning"
    return None  # Fully processed


async def scan_directory(progress_callback=None, cancel_check=None, on_file_discovered=None) -> dict:
    """Scan the photos directory and index all photos.

    Uses directory fingerprinting to skip unchanged directories on repeated scans:
    - First scan: walks all directories and caches fingerprints
    - Subsequent scans: only processes directories with changed fingerprints
    - Cache is cleared on app restart (in-memory only)

    Returns:
        dict with scan statistics and discovered files.
    """
    photos_dir = settings.photos_dir
    if not photos_dir.exists():
        logger.error("Photos directory does not exist: %s", photos_dir)
        return {"error": "Photos directory not found", "total": 0, "new": 0, "updated": 0, "discovered_files": {}}

    stats = {
        "total": 0,
        "new": 0,
        "updated": 0,
        "skipped": 0,
        "fully_processed": 0,
        "skipped_directories": 0,
        "errors": 0,
        "discovered_files": {},
    }

    # Phase 1: Collect all directories containing photos
    directories_with_photos: list[Path] = []
    for root, _dirs, files in os.walk(photos_dir):
        # Only include directories that have photo files
        if any(is_supported_photo(Path(root) / f) for f in files):
            directories_with_photos.append(Path(root))

    # Phase 2: Filter directories using fingerprint cache
    # This skips entire directories that haven't changed since the last scan.
    directories_to_process: list[Path] = []
    for dir_path in directories_with_photos:
        fingerprint = await asyncio.to_thread(_get_directory_fingerprint, dir_path)
        dir_key = str(dir_path)
        cached = _directory_cache.get(dir_key)
        if cached == fingerprint:
            stats["skipped_directories"] += 1
            continue  # Directory unchanged - skip entirely
        _directory_cache[dir_key] = fingerprint
        directories_to_process.append(dir_path)

    if stats["skipped_directories"] > 0:
        logger.info(
            "Directory fingerprinting: %d of %d directories unchanged (skipped)",
            stats["skipped_directories"],
            len(directories_with_photos),
        )

    # Phase 3: Collect photo files from changed directories only
    photo_files: list[Path] = []
    for dir_path in directories_to_process:
        for entry in dir_path.iterdir():
            if entry.is_file() and is_supported_photo(entry):
                photo_files.append(entry)

    stats["total"] = len(photo_files)
    logger.info("Found %d photo files in %d changed directories", stats["total"], len(directories_to_process))

    # Phase 4: Process files in batches
    discovered: dict[str, str] = {}
    batch_size = settings.batch_size
    cancelled = False
    for i in range(0, len(photo_files), batch_size):
        if cancel_check and cancel_check():
            logger.info("Scan cancelled by user")
            cancelled = True
            break
        batch = photo_files[i : i + batch_size]
        async with async_session() as session:
            # Track which files need pipeline processing and their entry points
            # (file_hash, file_path, entry_queue or None if skipped)
            pipeline_candidates: list[tuple[str, str, str | None]] = []

            for filepath in batch:
                try:
                    index_result = await _index_photo(session, filepath, stats)
                    if index_result:
                        file_hash, is_new = index_result
                        discovered[file_hash] = str(filepath)
                        if on_file_discovered:
                            photo = await session.get(Photo, file_hash)
                            if photo:
                                entry_point = _get_pipeline_entry_point(photo)
                                if entry_point:
                                    pipeline_candidates.append((file_hash, str(filepath), entry_point))
                                elif not is_new:
                                    stats["fully_processed"] += 1
                                elif is_new:
                                    pipeline_candidates.append((file_hash, str(filepath), "discovery"))
                except Exception:
                    logger.exception("Error indexing %s", filepath)
                    stats["errors"] += 1

                if progress_callback:
                    await progress_callback(
                        processed=i + batch.index(filepath) + 1,
                        total=stats["total"],
                        current_file=str(filepath),
                    )

            await session.commit()

        # Feed files to the pipeline AFTER the batch has been committed to the DB,
        # so that pipeline workers can find the Photo rows in their own sessions.
        # Callback receives (file_hash, file_path, entry_queue).
        if on_file_discovered:
            for file_hash, file_path, entry_queue in pipeline_candidates:
                if entry_queue:
                    await on_file_discovered(file_hash, file_path, entry_queue)

    stats["discovered_files"] = discovered

    # Clean up photos whose files no longer exist (skip if cancelled)
    if not cancelled:
        await _cleanup_removed_files()

    logger.info(
        "Scan complete: %d total, %d new, %d updated, %d skipped, %d fully_processed, %d skipped_dirs, %d errors",
        stats["total"],
        stats["new"],
        stats["updated"],
        stats["skipped"],
        stats["fully_processed"],
        stats["skipped_directories"],
        stats["errors"],
    )
    return stats


async def _index_photo(session: AsyncSession, filepath: Path, stats: dict) -> tuple[str, bool] | None:
    """Index a single photo file. Returns (file_hash, is_new) or None if skipped."""
    relative_path = str(filepath.relative_to(settings.photos_dir))

    # Get file metadata first (fast)
    file_stat = filepath.stat()
    file_size = file_stat.st_size
    file_mtime = file_stat.st_mtime

    # Check if this path already exists in PhotoPath
    path_result = await session.execute(
        select(PhotoPath).where(PhotoPath.file_path == relative_path)
    )
    existing_path = path_result.scalar_one_or_none()

    if existing_path:
        # Path exists - check if photo was modified
        existing_photo = await session.get(Photo, existing_path.file_hash)
        if existing_photo and existing_photo.file_size == file_size:
            # Check mtime if available (use 1-second tolerance for filesystem precision)
            if existing_photo.file_modified and abs(existing_photo.file_modified.timestamp() - file_mtime) < 1.0:
                # Photo unchanged on disk, but may still need pipeline processing
                # Return it so we can check if it needs more work
                stats["skipped"] += 1
                return (existing_path.file_hash, False)  # Existing photo, unchanged on disk

    # Compute file hash (slow - only when needed)
    file_hash = await asyncio.to_thread(compute_file_hash, filepath)

    # Check if this hash already exists (different path, same content)
    existing_by_hash = await session.get(Photo, file_hash)

    if existing_by_hash:
        # Photo content already known - just ensure the path is tracked
        path_result = await session.execute(
            select(PhotoPath).where(
                PhotoPath.file_hash == file_hash,
                PhotoPath.file_path == relative_path,
            )
        )
        if not path_result.scalar_one_or_none():
            session.add(PhotoPath(file_hash=file_hash, file_path=relative_path))
            # Update primary path if old one no longer exists
            old_path = settings.photos_dir / existing_by_hash.file_path
            if not old_path.exists():
                existing_by_hash.file_path = relative_path
            stats["updated"] += 1
        else:
            stats["skipped"] += 1
        return (file_hash, False)  # Existing photo

    # New photo
    mime_type, _ = mimetypes.guess_type(str(filepath))

    # Detect Live Photo / Motion Photo
    live_photo_video = None
    motion_photo = False

    video_path = await asyncio.to_thread(find_live_photo_video, filepath)
    if video_path:
        live_photo_video = str(video_path.relative_to(settings.photos_dir))

    if not live_photo_video:
        motion_photo = await asyncio.to_thread(detect_google_motion_photo, filepath)

    photo = Photo(
        file_hash=file_hash,
        file_path=relative_path,
        file_name=filepath.name,
        file_size=file_size,
        file_modified=datetime.fromtimestamp(file_mtime),
        mime_type=mime_type,
        live_photo_video=live_photo_video,
        motion_photo=motion_photo,
    )
    session.add(photo)

    # Also add to photo_paths
    session.add(PhotoPath(file_hash=file_hash, file_path=relative_path))

    stats["new"] += 1
    return (file_hash, True)  # New photo


async def _cleanup_removed_files() -> None:
    """Remove database entries for files that no longer exist on disk."""
    async with async_session() as session:
        result = await session.execute(select(PhotoPath))
        paths = result.scalars().all()

        removed_paths = []
        for photo_path in paths:
            full_path = settings.photos_dir / photo_path.file_path
            if not full_path.exists():
                removed_paths.append(photo_path)

        if removed_paths:
            for path in removed_paths:
                await session.delete(path)

            # Also remove photos that no longer have any paths
            for path in removed_paths:
                remaining = await session.execute(
                    select(PhotoPath).where(PhotoPath.file_hash == path.file_hash)
                )
                if not remaining.scalars().first():
                    photo = await session.get(Photo, path.file_hash)
                    if photo:
                        await session.delete(photo)

            await session.commit()
            logger.info("Cleaned up %d removed file paths", len(removed_paths))


async def index_single_file(filepath: Path) -> tuple[str, str] | None:
    """Index a single newly discovered file (from file watcher).

    Returns (file_hash, entry_queue) or None on error.
    New files always start at 'discovery'. Existing files start at their first incomplete stage.
    """
    if not is_supported_photo(filepath):
        return None

    try:
        stats = {"new": 0, "updated": 0, "skipped": 0, "errors": 0}
        async with async_session() as session:
            result = await _index_photo(session, filepath, stats)
            await session.commit()

        if result:
            file_hash, is_new = result
            if is_new:
                logger.info("Indexed new file: %s (%s)", filepath, file_hash)
                return (file_hash, "discovery")
            else:
                async with async_session() as session:
                    photo = await session.get(Photo, file_hash)
                    if photo:
                        entry_point = _get_pipeline_entry_point(photo)
                        if entry_point:
                            logger.info("Re-indexed existing file: %s (%s), entry: %s", filepath, file_hash, entry_point)
                            return (file_hash, entry_point)
                        else:
                            logger.debug("File already fully processed: %s", filepath)
                            return None
    except Exception:
        logger.exception("Error indexing file: %s", filepath)

    return None
