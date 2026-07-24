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
from backend.app.models import Photo, PhotoPath, PhotoHash, Face, Caption, StageFailure

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


def is_supported_video(filepath: Path) -> bool:
    """Check if a file is a supported standalone video format."""
    return filepath.suffix.lower() in settings.video_extensions


def is_indexable(filepath: Path) -> bool:
    return is_supported_photo(filepath) or is_supported_video(filepath)


def _is_live_photo_companion(filepath: Path) -> bool:
    """True if this video is the movie half of a Live Photo (a sibling
    photo shares its stem) — it's surfaced via the photo, not indexed alone."""
    if filepath.suffix.lower() not in {".mov"}:
        return False
    for ext in settings.photo_extensions:
        if filepath.with_suffix(ext).exists() or filepath.with_suffix(ext.upper()).exists():
            return True
    return False


def is_valid_image(filepath: Path) -> bool:
    """Check if file is a valid readable image (not corrupted).
    
    Returns False for:
    - Files too small to be valid images (< 1KB)
    - Truncated/corrupted images
    - Files that can't be opened
    """
    try:
        if filepath.stat().st_size < 1024:
            return False
        from PIL import Image
        with Image.open(filepath) as img:
            img.verify()
        return True
    except Exception:
        return False


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
    prefix = file_hash[:2]
    thumb_path = settings.thumbnails_dir / prefix / f"{file_hash}_200.webp"
    return thumb_path.exists()


# Directory mtime snapshot from the last completed scan. A directory's mtime
# changes when entries are added/removed/renamed, so an unchanged mtime means
# no files appeared or vanished inside it — those files can be skipped without
# a stat call each. Per-file stats dominate sweep cost on Docker bind mounts
# (~55s vs ~8s for 50k files / 2k dirs). In-memory only: the first sweep after
# a restart stats everything once, then pruning kicks in.
_dir_snapshot: dict[str, float] = {}


def _collect_photo_files(
    photos_dir: Path, cancel_check=None, dir_snapshot: dict[str, float] | None = None
) -> tuple[list[tuple[Path, os.stat_result]], set[str], dict[str, float]]:
    """Walk the photos directory; stat files only in changed directories.

    Runs in a worker thread — must not touch the event loop or the database.
    When dir_snapshot is None every directory counts as changed (full scan).
    Note: in-place content edits don't bump the parent dir's mtime, so pruned
    sweeps miss them — only a full rescan re-checks unchanged directories.

    Returns (files_to_check, seen_relative_paths, new_snapshot).
    """
    to_check: list[tuple[Path, os.stat_result]] = []
    seen: set[str] = set()
    new_snapshot: dict[str, float] = {}
    for root, dirs, files in os.walk(photos_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        try:
            dir_mtime = os.stat(root).st_mtime
        except OSError:
            continue
        new_snapshot[root] = dir_mtime
        prev_mtime = dir_snapshot.get(root) if dir_snapshot is not None else None
        dir_unchanged = prev_mtime is not None and abs(prev_mtime - dir_mtime) < 1.0
        for f in files:
            filepath = Path(root) / f
            if not is_indexable(filepath):
                continue
            # Apple Live Photo movies (.mov beside a photo) are surfaced via
            # the photo itself, so never index them as standalone videos.
            if is_supported_video(filepath) and _is_live_photo_companion(filepath):
                continue
            seen.add(str(filepath.relative_to(photos_dir)))
            if dir_unchanged:
                continue
            try:
                file_stat = filepath.stat()
            except OSError:
                continue
            if file_stat.st_size < 1024:
                continue
            to_check.append((filepath, file_stat))
        if cancel_check and cancel_check():
            break
    return to_check, seen, new_snapshot


async def scan_directory(
    progress_callback=None, cancel_check=None, on_file_discovered=None, fast: bool = False
) -> dict:
    """Scan the photos directory and index all photos.

    For each photo, determine which pipeline stages need processing based on:
    - Config flags (ENABLE_*)
    - Actual data/file existence

    Args:
        progress_callback: async callback(processed, total, current_file)
        cancel_check: function returning True if scan should be cancelled
        on_file_discovered: async callback(file_hash, entry_stage) when file needs processing
        fast: only pick up new/changed/removed files; skip unchanged photos
            entirely instead of re-checking their processing stages. Used by
            the periodic background sweep.

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

    # Walk + stat in a worker thread: on Docker bind mounts each filesystem
    # call is slow, and doing 40k of them on the event loop freezes the API.
    # Fast sweeps prune via the dir-mtime snapshot; full rescans check all.
    global _dir_snapshot
    dir_snapshot = dict(_dir_snapshot) if fast else None
    photo_files, seen_paths, new_snapshot = await asyncio.to_thread(
        _collect_photo_files, photos_dir, cancel_check, dir_snapshot
    )
    if cancel_check and cancel_check():
        logger.info("Scan cancelled during file collection")
        return stats

    stats["total"] = len(seen_paths)
    stats["skipped"] += len(seen_paths) - len(photo_files)
    logger.info(
        "Found %d photo files, %d in changed directories", len(seen_paths), len(photo_files)
    )

    # One query for all known paths beats per-file lookups at this scale.
    known: dict[str, tuple[int, float]] = {}
    async with async_session() as session:
        result = await session.execute(
            select(PhotoPath.file_path, Photo.file_size, Photo.file_modified).join(
                Photo, Photo.file_hash == PhotoPath.file_hash
            )
        )
        for rel_path, size, modified in result.all():
            known[rel_path] = (size, modified.timestamp() if modified else 0.0)

    # A directory is only recorded in the snapshot when everything in it was
    # handled cleanly — a dir with errors (e.g. a file still being copied)
    # gets re-checked on the next sweep.
    cancelled = False
    error_dirs: set[str] = set()
    for i, (filepath, file_stat) in enumerate(photo_files):
        if cancel_check and cancel_check():
            logger.info("Scan cancelled by user")
            cancelled = True
            break

        rel_path = str(filepath.relative_to(photos_dir))

        entry = known.get(rel_path)
        unchanged = (
            entry is not None
            and entry[0] == file_stat.st_size
            and entry[1]
            and abs(entry[1] - file_stat.st_mtime) < 1.0
        )

        # Fast sweeps only look for new/changed/removed files; re-queueing
        # incomplete stages of unchanged photos is the full rescan's job.
        if unchanged and fast:
            stats["skipped"] += 1
            continue

        # Validity (PIL verify) is expensive and image-only — only check photos
        # we might index. Videos can't be opened by PIL; they're validated later
        # when their poster frame is extracted.
        if (
            not unchanged
            and not is_supported_video(filepath)
            and not await asyncio.to_thread(is_valid_image, filepath)
        ):
            stats["errors"] += 1
            error_dirs.add(str(filepath.parent))
            continue

        try:
            async with async_session() as session:
                entry_stage = await _index_photo(session, filepath, stats, file_stat)
                await session.commit()

                if entry_stage and on_file_discovered:
                    file_hash = entry_stage[0]
                    stage = entry_stage[1]
                    await on_file_discovered(file_hash, stage)
        except Exception as e:
            logger.warning("Skipping %s: %s", filepath, type(e).__name__)
            stats["errors"] += 1
            error_dirs.add(str(filepath.parent))

        if progress_callback and ((i + 1) % 200 == 0 or i + 1 == len(photo_files)):
            await progress_callback(
                processed=i + 1,
                total=len(photo_files),
                current_file=str(filepath),
            )

    if not cancelled:
        await _cleanup_removed_files(seen_paths)
        _dir_snapshot = {
            d: mtime for d, mtime in new_snapshot.items() if d not in error_dirs
        }

    logger.info(
        "Scan complete: %d total, %d new, %d updated, %d skipped, %d errors",
        stats["total"],
        stats["new"],
        stats["updated"],
        stats["skipped"],
        stats["errors"],
    )
    return stats


async def _index_photo(
    session: AsyncSession, filepath: Path, stats: dict, file_stat: os.stat_result | None = None
) -> tuple[str, str] | None:
    """Index a single photo file.

    Returns:
        (file_hash, entry_stage) if photo needs processing
        None if photo is fully processed or not indexed
    """
    from backend.app.workers.queues import QueueType

    relative_path = str(filepath.relative_to(settings.photos_dir))
    if file_stat is None:
        file_stat = await asyncio.to_thread(filepath.stat)
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

    # New file - create record
    mime_type, _ = mimetypes.guess_type(str(filepath))
    is_video = is_supported_video(filepath)

    if is_video:
        from backend.app.services.video import extract_video_metadata

        meta = await asyncio.to_thread(extract_video_metadata, filepath)
        photo = Photo(
            file_hash=file_hash,
            file_path=relative_path,
            file_name=filepath.name,
            file_size=file_size,
            file_modified=datetime.fromtimestamp(file_mtime),
            mime_type=mime_type or "video/mp4",
            is_video=True,
            duration=meta.get("duration"),
            width=meta.get("width"),
            height=meta.get("height"),
        )
        session.add(photo)
        session.add(PhotoPath(file_hash=file_hash, file_path=relative_path))
        stats["new"] += 1
        # Videos only need a poster thumbnail.
        return (file_hash, "thumbnails")

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
    """Determine which pipeline stage a photo should enter (async version).

    Stages with a recorded permanent failure are skipped — without this,
    photos that can never complete a stage get re-queued on every scan.
    """
    # Videos only need a poster thumbnail; all other stages are image-only.
    if photo.is_video:
        if not thumb_exists(photo.file_hash):
            failed_result = await session.execute(
                select(StageFailure.stage).where(StageFailure.file_hash == photo.file_hash)
            )
            if "thumbnails" not in {row[0] for row in failed_result}:
                return "thumbnails"
        return None

    failed_result = await session.execute(
        select(StageFailure.stage).where(StageFailure.file_hash == photo.file_hash)
    )
    failed = {row[0] for row in failed_result}

    # EXIF is always enabled (core functionality)
    if "exif" not in failed and photo.camera_make is None and photo.date_taken is None:
        return "exif"

    # Geocoding
    if settings.ENABLE_GEOCODING and "geocoding" not in failed:
        if photo.location_city is None and photo.gps_latitude is not None:
            return "geocoding"

    # Thumbnails always enabled (core functionality)
    if "thumbnails" not in failed and not thumb_exists(photo.file_hash):
        return "thumbnails"

    # Hashing always enabled (core functionality)
    if "hashing" not in failed:
        result = await session.execute(
            select(PhotoHash).where(PhotoHash.file_hash == photo.file_hash)
        )
        if result.scalar_one_or_none() is None:
            return "hashing"

    # Faces
    if settings.ENABLE_FACE_DETECTION and "faces" not in failed:
        result = await session.execute(
            select(func.count(Face.file_hash)).where(Face.file_hash == photo.file_hash)
        )
        if (result.scalar() or 0) == 0:
            return "faces"

    # Captioning
    if settings.ENABLE_CAPTIONING and "captioning" not in failed:
        result = await session.execute(
            select(Caption).where(Caption.file_hash == photo.file_hash)
        )
        if result.scalar_one_or_none() is None:
            return "captioning"

    return None


async def _cleanup_removed_files(seen_paths: set[str] | None = None) -> None:
    """Remove database entries for files that no longer exist on disk.

    When the caller provides the set of paths seen during its walk, only the
    paths missing from that set are stat-checked — at 40k photos, exists()
    on every DB path over a Docker bind mount is far too slow.
    """
    async with async_session() as session:
        result = await session.execute(select(PhotoPath))
        paths = result.scalars().all()

        candidates = (
            [p for p in paths if p.file_path not in seen_paths]
            if seen_paths is not None
            else list(paths)
        )

        def _missing_on_disk(candidate_paths):
            return [
                p for p in candidate_paths
                if not (settings.photos_dir / p.file_path).exists()
            ]

        removed_paths = await asyncio.to_thread(_missing_on_disk, candidates)

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
    
    if not is_valid_image(filepath):
        logger.warning("Skipping corrupted/invalid image: %s", filepath)
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
    except Exception as e:
        logger.warning("Skipping %s: %s", filepath, type(e).__name__)
        return None