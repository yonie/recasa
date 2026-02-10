"""File scanner service - discovers and indexes photos from the watch directory."""

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


async def scan_directory(progress_callback=None, cancel_check=None, on_file_discovered=None) -> dict:
    """Scan the photos directory and index all photos.

    Returns:
        dict with scan statistics and discovered files.
    """
    photos_dir = settings.photos_dir
    if not photos_dir.exists():
        logger.error("Photos directory does not exist: %s", photos_dir)
        return {"error": "Photos directory not found", "total": 0, "new": 0, "updated": 0, "discovered_files": {}}

    stats = {"total": 0, "new": 0, "updated": 0, "skipped": 0, "errors": 0, "discovered_files": {}}

    # Collect all photo files
    photo_files: list[Path] = []
    for root, _dirs, files in os.walk(photos_dir):
        for filename in files:
            filepath = Path(root) / filename
            if is_supported_photo(filepath):
                photo_files.append(filepath)

    stats["total"] = len(photo_files)
    logger.info("Found %d photo files in %s", stats["total"], photos_dir)

    # Collect discovered files for pipeline
    discovered: dict[str, str] = {}

    # Process in batches
    batch_size = settings.batch_size
    cancelled = False
    for i in range(0, len(photo_files), batch_size):
        if cancel_check and cancel_check():
            logger.info("Scan cancelled by user")
            cancelled = True
            break
        batch = photo_files[i : i + batch_size]
        async with async_session() as session:
            # Track which files need pipeline processing (determined after commit)
            pipeline_candidates: list[tuple[str, str]] = []

            for filepath in batch:
                try:
                    file_hash = await _index_photo(session, filepath, stats)
                    if file_hash:
                        discovered[file_hash] = str(filepath)
                        if on_file_discovered:
                            photo = await session.get(Photo, file_hash)
                            if photo and _needs_pipeline_processing(photo):
                                pipeline_candidates.append((file_hash, str(filepath)))
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
        if on_file_discovered:
            for file_hash, file_path in pipeline_candidates:
                await on_file_discovered(file_hash, file_path)

    stats["discovered_files"] = discovered

    # Clean up photos whose files no longer exist (skip if cancelled)
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


async def _index_photo(session: AsyncSession, filepath: Path, stats: dict) -> str | None:
    """Index a single photo file. Returns file_hash or None if skipped."""
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
                # Photo unchanged - skip entirely
                stats["skipped"] += 1
                return None
            # Size matches but mtime different - will update file_modified below

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
        return file_hash

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
    return file_hash


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


async def index_single_file(filepath: Path) -> str | None:
    """Index a single newly discovered file. Returns file_hash or None on error."""
    if not is_supported_photo(filepath):
        return None

    try:
        stats = {"new": 0, "updated": 0, "skipped": 0, "errors": 0}
        async with async_session() as session:
            await _index_photo(session, filepath, stats)
            await session.commit()

        if stats["new"]:
            file_hash = await asyncio.to_thread(compute_file_hash, filepath)
            logger.info("Indexed new file: %s (%s)", filepath, file_hash)
            return file_hash
    except Exception:
        logger.exception("Error indexing file: %s", filepath)

    return None
