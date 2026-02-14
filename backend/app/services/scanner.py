"""File scanner service - discovers and indexes photos from the watch directory.

Smart rescan behavior:
- New files: enter pipeline at appropriate stage based on missing data
- Existing files: check each stage's output existence, queue if missing
- Config flags control which stages are enabled
- No boolean flags in DB - actual data/file existence determines state
"""

import asyncio
import hashlib
import logging
import mimetypes
import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import settings
from backend.app.database import async_session
from backend.app.models import Photo, PhotoPath, PhotoHash, Face, Caption

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


def thumb_exists(file_hash: str) -> bool:
    """Check if thumbnail file exists."""
    return (settings.thumbnails_dir / f"{file_hash}_200.jpg").exists()


async def scan_directory(progress_callback=None, cancel_check=None, on_file_discovered=None) -> dict:
    """Scan the photos directory and index all photos.

    For each photo, determine which pipeline stages need processing based on:
    - Config flags (ENABLE_*)
    - Actual data/file existence

    Args:
        progress_callback: async callback(processed, total, current_file)
        cancel_check: function returning True if scan should be cancelled
        on_file_discovered: async callback(file_hash, entry_stage) when file needs processing

    Returns:
        dict with scan statistics.
    """
    photos_dir = settings.photos_dir
    if not photos_dir.exists():
        logger.error("Photos directory does not exist: %s", photos_dir)
        return {"error": "Photos directory not found", "total": 0, "discovered_files": {}}

    stats = {
        "total": 0,
        "new": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
        "discovered_files": {},
    }

    # Collect all photo files, skipping hidden directories
    photo_files: list[Path] = []
    for root, dirs, files in os.walk(photos_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            filepath = Path(root) / f
            if is_supported_photo(filepath):
                photo_files.append(filepath)
        if cancel_check and cancel_check():
            logger.info("Scan cancelled during file collection")
            return stats

    stats["total"] = len(photo_files)
    logger.info("Found %d photo files", stats["total"])

    # Process files in batches
    cancelled = False
    for i, filepath in enumerate(photo_files):
        if cancel_check and cancel_check():
            logger.info("Scan cancelled by user")
            cancelled = True
            break

        try:
            async with async_session() as session:
                entry_stage = await _index_photo(session, filepath, stats)
                await session.commit()

                if entry_stage and on_file_discovered:
                    file_hash = entry_stage[0]
                    stage = entry_stage[1]
                    await on_file_discovered(file_hash, stage)
        except Exception:
            logger.exception("Error indexing %s", filepath)
            stats["errors"] += 1

        if progress_callback:
            await progress_callback(
                processed=i + 1,
                total=stats["total"],
                current_file=str(filepath),
            )

    if not cancelled:
        await _cleanup_removed_files()

    logger.info(
        "Scan complete: %d total, %d new, %d updated, %d skipped, %d errors",
        stats["total"],
        stats["new"],
        stats["updated"],
        stats["skipped"],
        stats["errors"],
    )
    return stats


async def _index_photo(session: AsyncSession, filepath: Path, stats: dict) -> tuple[str, str] | None:
    """Index a single photo file.

    Returns:
        (file_hash, entry_stage) if photo needs processing
        None if photo is fully processed or not indexed
    """
    from backend.app.workers.queues import QueueType

    relative_path = str(filepath.relative_to(settings.photos_dir))
    file_stat = filepath.stat()
    file_size = file_stat.st_size
    file_mtime = file_stat.st_mtime

    # Check if photo already indexed by path
    path_result = await session.execute(
        select(PhotoPath).where(PhotoPath.file_path == relative_path)
    )
    existing_path = path_result.scalar_one_or_none()

    if existing_path:
        existing_photo = await session.get(Photo, existing_path.file_hash)
        if existing_photo and existing_photo.file_size == file_size:
            if existing_photo.file_modified and abs(existing_photo.file_modified.timestamp() - file_mtime) < 1.0:
                # File unchanged - check if any processing is needed
                entry_stage = await _get_entry_stage_async(existing_photo, session)
                if entry_stage:
                    return (existing_path.file_hash, entry_stage)
                stats["skipped"] += 1
                return None

    # Compute hash
    file_hash = await asyncio.to_thread(compute_file_hash, filepath)

    # Check if photo exists by hash
    existing_by_hash = await session.get(Photo, file_hash)

    if existing_by_hash:
        # Update path if needed
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

        # Check if processing is needed
        entry_stage = await _get_entry_stage_async(existing_by_hash, session)
        if entry_stage:
            return (file_hash, entry_stage)
        return None

    # New photo - create record
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

    # New photos always start at EXIF (core functionality, always enabled)
    return (file_hash, "exif")


async def _get_entry_stage_async(photo: Photo, session) -> str | None:
    """Determine which pipeline stage a photo should enter (async version)."""
    # EXIF is always enabled (core functionality)
    if photo.camera_make is None and photo.date_taken is None:
        return "exif"

    # Geocoding
    if settings.ENABLE_GEOCODING:
        if photo.location_city is None and photo.gps_latitude is not None:
            return "geocoding"

    # Thumbnails always enabled (core functionality)
    if not thumb_exists(photo.file_hash):
        return "thumbnails"

    # Hashing always enabled (core functionality) 
    result = await session.execute(
        select(PhotoHash).where(PhotoHash.file_hash == photo.file_hash)
    )
    if result.scalar_one_or_none() is None:
        return "hashing"

    # Faces
    if settings.ENABLE_FACE_DETECTION:
        result = await session.execute(
            select(func.count(Face.file_hash)).where(Face.file_hash == photo.file_hash)
        )
        if (result.scalar() or 0) == 0:
            return "faces"

    # Captioning
    if settings.ENABLE_CAPTIONING:
        result = await session.execute(
            select(Caption).where(Caption.file_hash == photo.file_hash)
        )
        if result.scalar_one_or_none() is None:
            return "captioning"

    return None


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

    Returns (file_hash, entry_stage) or None if file not supported/unchanged.
    """
    if not is_supported_photo(filepath):
        return None

    try:
        stats = {"new": 0, "updated": 0, "skipped": 0, "errors": 0}
        async with async_session() as session:
            result = await _index_photo(session, filepath, stats)
            await session.commit()

        if result:
            file_hash, entry_stage = result
            logger.info("Indexed new file: %s (%s) -> %s", filepath, file_hash, entry_stage)
            return (file_hash, entry_stage)
        return None
    except Exception:
        logger.exception("Error indexing file: %s", filepath)
        return None