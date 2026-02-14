"""File scanner service - discovers and indexes photos from the watch directory.

Smart rescan behavior:
- New files: enter pipeline at EXIF (full processing)
- Existing fully-processed files: skipped entirely (via mtime/size check)
- Existing partially-processed files: enter at first incomplete stage
- Removed files: deleted from DB during cleanup pass

The database is the source of truth for processing state.
Skips hidden directories (starting with .) during scan.
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

HASH_BUFFER_SIZE = 65536


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
    for ext in [".mov", ".MOV"]:
        video_path = photo_path.with_suffix(ext)
        if video_path.exists():
            return video_path
    return None


def detect_google_motion_photo(filepath: Path) -> bool:
    """Check if a JPEG contains embedded Google Motion Photo data."""
    if filepath.suffix.lower() not in {".jpg", ".jpeg"}:
        return False

    try:
        with open(filepath, "rb") as f:
            f.seek(0, 2)
            file_size = f.tell()
            if file_size < 1024:
                return False

            search_size = min(file_size, 4 * 1024 * 1024)
            f.seek(file_size - search_size)
            data = f.read(search_size)

            return b"ftypmp4" in data or b"ftypisom" in data or b"MotionPhoto" in data
    except OSError:
        return False


def _get_pipeline_entry_point(photo: Photo) -> str | None:
    """Determine which pipeline stage a photo should enter.

    Returns the queue name for the first incomplete stage, or None if fully processed.
    Pipeline order: EXIF → GEOCODING → THUMBNAILS → MOTION_PHOTOS → HASHING → FACES → CAPTIONING → EVENTS
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
    return None


async def scan_directory(progress_callback=None, cancel_check=None, on_file_discovered=None, discovery_callback=None) -> dict:
    """Scan the photos directory and index all photos.

    Skips hidden directories (starting with .).
    Uses mtime/size check to skip unchanged files (no separate fingerprint cache needed).

    Args:
        progress_callback: async callback(processed, total, current_file) for scan progress
        cancel_check: function returning True if scan should be cancelled
        on_file_discovered: async callback(file_hash, file_path, entry_queue) when file needs processing
        discovery_callback: async callback(phase, **kwargs) for discovery phase progress

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
        "requeued": 0,
        "fully_processed": 0,
        "errors": 0,
        "discovered_files": {},
    }

    # Phase 1: Collect all photo files, skipping hidden directories
    photo_files: list[Path] = []
    for root, dirs, files in os.walk(photos_dir):
        # Skip hidden directories (modify dirs in-place to affect os.walk)
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        
        for f in files:
            filepath = Path(root) / f
            if is_supported_photo(filepath):
                photo_files.append(filepath)
        
        if discovery_callback:
            await discovery_callback("collecting_files", files_collected=len(photo_files))
        
        if cancel_check and cancel_check():
            logger.info("Scan cancelled during file collection")
            return stats

    stats["total"] = len(photo_files)
    logger.info("Found %d photo files", stats["total"])

    # Phase 2: Process files in batches
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
            pipeline_candidates: list[tuple[str, str, str]] = []

            for filepath in batch:
                try:
                    index_result = await _index_photo(session, filepath, stats)
                    if index_result:
                        file_hash, is_new, entry_point = index_result
                        discovered[file_hash] = str(filepath)
                        if on_file_discovered:
                            if entry_point:
                                pipeline_candidates.append((file_hash, str(filepath), entry_point))
                            elif not is_new:
                                stats["fully_processed"] += 1
                            elif is_new:
                                pipeline_candidates.append((file_hash, str(filepath), "exif"))
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

        if on_file_discovered:
            for file_hash, file_path, entry_queue in pipeline_candidates:
                await on_file_discovered(file_hash, file_path, entry_queue)

    stats["discovered_files"] = discovered

    if not cancelled:
        await _cleanup_removed_files()

    logger.info(
        "Scan complete: %d total, %d new, %d updated, %d skipped, %d requeued, %d fully_processed, %d errors",
        stats["total"],
        stats["new"],
        stats["updated"],
        stats["skipped"],
        stats["requeued"],
        stats["fully_processed"],
        stats["errors"],
    )
    return stats


async def _index_photo(session: AsyncSession, filepath: Path, stats: dict) -> tuple[str, bool, str | None] | None:
    """Index a single photo file. 
    
    Returns:
        (file_hash, is_new, entry_point) - file needs processing, entry_point is the first incomplete stage
        (file_hash, False, None) - file already indexed and fully processed
        None - file was skipped (unchanged and fully processed)
    """
    relative_path = str(filepath.relative_to(settings.photos_dir))

    file_stat = filepath.stat()
    file_size = file_stat.st_size
    file_mtime = file_stat.st_mtime

    path_result = await session.execute(
        select(PhotoPath).where(PhotoPath.file_path == relative_path)
    )
    existing_path = path_result.scalar_one_or_none()

    if existing_path:
        existing_photo = await session.get(Photo, existing_path.file_hash)
        if existing_photo and existing_photo.file_size == file_size:
            if existing_photo.file_modified and abs(existing_photo.file_modified.timestamp() - file_mtime) < 1.0:
                # File unchanged - check if processing is incomplete
                entry_point = _get_pipeline_entry_point(existing_photo)
                if entry_point:
                    # Needs processing - return hash and entry point so caller can queue it
                    stats["requeued"] += 1
                    return (existing_path.file_hash, False, entry_point)
                # Fully processed - skip entirely
                stats["skipped"] += 1
                return None

    file_hash = await asyncio.to_thread(compute_file_hash, filepath)

    existing_by_hash = await session.get(Photo, file_hash)

    if existing_by_hash:
        path_result = await session.execute(
            select(PhotoPath).where(
                PhotoPath.file_hash == file_hash,
                PhotoPath.file_path == relative_path,
            )
        )
        if not path_result.scalar_one_or_none():
            session.add(PhotoPath(file_hash=file_hash, file_path=relative_path))
            old_path = settings.photos_dir / existing_by_hash.file_path
            if not old_path.exists():
                existing_by_hash.file_path = relative_path
            stats["updated"] += 1
        else:
            stats["skipped"] += 1
        # Check if this existing photo needs processing
        entry_point = _get_pipeline_entry_point(existing_by_hash)
        return (file_hash, False, entry_point)

    mime_type, _ = mimetypes.guess_type(str(filepath))

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
    session.add(PhotoPath(file_hash=file_hash, file_path=relative_path))

    stats["new"] += 1
    return (file_hash, True, "exif")


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
    """
    if not is_supported_photo(filepath):
        return None

    try:
        stats = {"new": 0, "updated": 0, "skipped": 0, "requeued": 0, "errors": 0}
        async with async_session() as session:
            result = await _index_photo(session, filepath, stats)
            await session.commit()

        if result:
            file_hash, is_new, entry_point = result
            if is_new:
                logger.info("Indexed new file: %s (%s)", filepath, file_hash)
                return (file_hash, "exif")
            elif entry_point:
                logger.info("Re-indexed existing file: %s (%s), entry: %s", filepath, file_hash, entry_point)
                return (file_hash, entry_point)
            else:
                logger.debug("File already fully processed: %s", filepath)
                return None
    except Exception:
        logger.exception("Error indexing file: %s", filepath)

    return None