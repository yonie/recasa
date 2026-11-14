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
import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import settings
from backend.app.database import async_session
from backend.app.models import Photo, PhotoPath
from backend.app.workers.stages import (
    PhotoFacts,
    StageOutputs,
    first_needed_stage,
    load_photo_facts,
    load_stage_outputs,
)

# Register MIME types for formats Python's mimetypes module doesn't know.
mimetypes.add_type("image/x-olympus-orf", ".orf")

logger = logging.getLogger(__name__)

# Index writes (new photos, new paths, cleanup) from the periodic sweep and
# the file watcher go through this lock. Both can meet the same new file at
# the same moment, and two sessions inserting it race to an IntegrityError.
_index_lock = asyncio.Lock()


def compute_file_hash(filepath: Path) -> str:
    """Compute SHA-256 hash of a file."""
    with open(filepath, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def is_supported_photo(filepath: Path) -> bool:
    """Check if a file is a supported photo format."""
    return filepath.suffix.lower() in settings.photo_extensions


def is_supported_video(filepath: Path) -> bool:
    """Check if a file is a supported standalone video format."""
    return filepath.suffix.lower() in settings.video_extensions


def is_indexable(filepath: Path) -> bool:
    return is_supported_photo(filepath) or is_supported_video(filepath)


def _is_live_photo_companion(filepath: Path, siblings: set[str] | None = None) -> bool:
    """True if this video is the movie half of a Live Photo (a sibling
    photo shares its stem): it's surfaced via the photo, not indexed alone.

    `siblings` are the names in the same directory when the caller already
    listed it; a hit there answers without the per-extension stat calls.
    """
    if filepath.suffix.lower() not in {".mov"}:
        return False
    candidates = [
        filepath.with_suffix(variant)
        for ext in settings.photo_extensions
        for variant in (ext, ext.upper())
    ]
    if siblings is not None and any(c.name in siblings for c in candidates):
        return True
    return any(c.exists() for c in candidates)


# Apple Live Photo movies carry this QuickTime metadata key (and a paired
# still-image-time track); genuine videos never do. Reliably distinguishes a
# Live Photo movie from a deliberately-recorded short clip, even when the
# still half isn't present in the library. See:
# https://www.whexy.com/dyn/ec968903-2fab-44ac-8003-62d14cacc2f5
_LIVE_PHOTO_MARKER = b"com.apple.quicktime.content.identifier"


def is_live_photo_movie(filepath: Path) -> bool:
    """Detect an Apple Live Photo movie by its content-identifier marker.

    The marker lives in the moov atom, which QuickTime places at either the
    start or the end of the file, so scan a 1 MB chunk from each end rather
    than reading the whole (possibly huge) file.
    """
    if filepath.suffix.lower() != ".mov":
        return False
    chunk = 1024 * 1024
    try:
        size = filepath.stat().st_size
        with open(filepath, "rb") as f:
            data = f.read(chunk)
            if size > chunk * 2:
                f.seek(-chunk, 2)
                data += f.read(chunk)
        return _LIVE_PHOTO_MARKER in data
    except OSError:
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
        from backend.app.services.image_loader import is_raw
        if is_raw(filepath):
            # For RAW (ORF), opening with rawpy confirms the file is parseable;
            # we use the lightweight sizes path rather than full pixel decode.
            import rawpy as _rawpy  # type: ignore[import-not-found]
            with _rawpy.imread(str(filepath)) as raw:
                return raw.sizes.width > 0 and raw.sizes.height > 0
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


# Directory mtime snapshot from the last completed scan. A directory's mtime
# changes when entries are added/removed/renamed, so an unchanged mtime means
# no files appeared or vanished inside it: those files can be skipped without
# a stat call each. Per-file stats dominate sweep cost on Docker bind mounts
# (~55s vs ~8s for 50k files / 2k dirs). In-memory only: the first sweep after
# a restart stats everything once, then pruning kicks in.
_dir_snapshot: dict[str, float] = {}

# Relative paths the last completed scan saw. A file in an "unchanged"
# directory that is not in here is checked anyway: two changes within the
# mtime tolerance of each other leave the directory's mtime looking the same.
_seen_snapshot: set[str] = set()

# Two mtimes within this many seconds count as equal (FAT and SMB round).
_MTIME_TOLERANCE = 1.0


# Syncthing's in-flight downloads. The ".syncthing.*" form is already hidden.
_SYNCTHING_TEMP = re.compile(r"^(~syncthing~|\.syncthing\.).*\.tmp$", re.IGNORECASE)


def is_library_name(name: str) -> bool:
    """Whether a single path component can be part of the library.

    Dot-files and dot-directories are not: Syncthing keeps old versions in
    .stversions, NAS boxes keep thumbnail caches in dot-directories, macOS
    writes ._ AppleDouble files. Neither are Syncthing temp files.
    """
    return not name.startswith(".") and not _SYNCTHING_TEMP.match(name)


def is_library_path(relative_path: str | Path) -> bool:
    """The one test for "may this library-relative path be indexed?".

    Shared by the sweep, the file watcher and cleanup: an indexed path that
    fails it is removed from the index like a deleted file.
    """
    return all(is_library_name(part) for part in Path(relative_path).parts)


def _inside_library(entry_path: str, library_root: Path) -> bool:
    """False for a symlink that leads out of the library. Never follows one
    out of /photos, whatever a link inside it points at."""
    try:
        return Path(entry_path).resolve().is_relative_to(library_root)
    except (OSError, RuntimeError):
        return False


def _mtime_equal(a: float, b: float) -> bool:
    return abs(a - b) < _MTIME_TOLERANCE


def _walk_library(photos_dir: Path) -> Iterator[tuple[str, list[os.DirEntry]]]:
    """Top-down walk yielding (directory, library files in it).

    Like os.walk(followlinks=False) in the same order, minus hidden and temp
    entries, and handing out DirEntry objects so symlinks are recognised
    without an extra stat per file. Unreadable directories are skipped.
    """
    stack = [str(photos_dir)]
    while stack:
        root = stack.pop()
        try:
            with os.scandir(root) as it:
                entries = list(it)
        except OSError:
            continue
        subdirs: list[str] = []
        files: list[os.DirEntry] = []
        for entry in entries:
            if not is_library_name(entry.name):
                continue
            try:
                is_dir = entry.is_dir()
            except OSError:
                continue
            if is_dir:
                if not entry.is_symlink():  # never descend through a link
                    subdirs.append(entry.path)
            else:
                files.append(entry)
        yield root, files
        stack.extend(reversed(subdirs))


def _collect_photo_files(
    photos_dir: Path,
    cancel_check=None,
    dir_snapshot: dict[str, float] | None = None,
    prev_seen: set[str] | frozenset[str] = frozenset(),
) -> tuple[list[tuple[Path, os.stat_result]], set[str], dict[str, float]]:
    """Walk the photos directory; stat files only in changed directories.

    Runs in a worker thread: must not touch the event loop or the database.
    When dir_snapshot is None every directory counts as changed (full scan).
    Files in unchanged directories are still checked when prev_seen (the
    previous scan's paths) does not have them.
    Note: in-place content edits don't bump the parent dir's mtime, so pruned
    sweeps miss them; only a full rescan re-checks unchanged directories.

    Returns (files_to_check, seen_relative_paths, new_snapshot).
    """
    to_check: list[tuple[Path, os.stat_result]] = []
    seen: set[str] = set()
    new_snapshot: dict[str, float] = {}
    library_root = photos_dir.resolve()
    for root, files in _walk_library(photos_dir):
        try:
            dir_mtime = os.stat(root).st_mtime
        except OSError:
            continue
        new_snapshot[root] = dir_mtime
        prev_mtime = dir_snapshot.get(root) if dir_snapshot is not None else None
        dir_unchanged = prev_mtime is not None and _mtime_equal(prev_mtime, dir_mtime)
        siblings = {entry.name for entry in files}
        for entry in files:
            filepath = Path(entry.path)
            if not is_indexable(filepath):
                continue
            if entry.is_symlink() and not _inside_library(entry.path, library_root):
                continue
            # Never index Apple Live Photo movies as standalone videos: those
            # beside their still (same folder) OR carrying the Live Photo
            # marker (still elsewhere or absent). Genuine short clips lack the
            # marker and are kept.
            if is_supported_video(filepath) and (
                _is_live_photo_companion(filepath, siblings) or is_live_photo_movie(filepath)
            ):
                continue
            rel_path = str(filepath.relative_to(photos_dir))
            seen.add(rel_path)
            if dir_unchanged and rel_path in prev_seen:
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


# Known indexed paths: relative path -> [(file_hash, size, mtime timestamp)].
# Usually one entry; a file edited in place keeps an entry per content
# version (see _index_photo).
KnownPaths = dict[str, list[tuple[str, int, float]]]


async def _load_known_paths() -> KnownPaths:
    """One query for all known paths beats per-file lookups at this scale."""
    known: KnownPaths = {}
    async with async_session() as session:
        result = await session.execute(
            select(PhotoPath.file_path, Photo.file_hash, Photo.file_size, Photo.file_modified)
            .join(Photo, Photo.file_hash == PhotoPath.file_hash)
        )
        for rel_path, file_hash, size, modified in result:
            known.setdefault(rel_path, []).append(
                (file_hash, size, modified.timestamp() if modified else 0.0)
            )
    return known


def _unchanged_hash(entries, file_stat: os.stat_result) -> str | None:
    """The indexed photo this path still holds, if size and mtime match one."""
    for file_hash, size, mtime in entries or ():
        if size == file_stat.st_size and mtime and _mtime_equal(mtime, file_stat.st_mtime):
            return file_hash
    return None


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
    global _dir_snapshot, _seen_snapshot

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
    dir_snapshot = dict(_dir_snapshot) if fast else None
    prev_seen = _seen_snapshot
    photo_files, seen_paths, new_snapshot = await asyncio.to_thread(
        _collect_photo_files, photos_dir, cancel_check, dir_snapshot, prev_seen
    )
    if cancel_check and cancel_check():
        logger.info("Scan cancelled during file collection")
        return stats

    stats["total"] = len(seen_paths)
    stats["skipped"] += len(seen_paths) - len(photo_files)
    logger.info(
        "Found %d photo files, %d in changed directories", len(seen_paths), len(photo_files)
    )

    if fast and not photo_files and seen_paths == prev_seen:
        # The common periodic sweep: no file to check and exactly the files
        # of the last scan, so nothing to index and nothing removed. Skip the
        # two whole-index queries below.
        _dir_snapshot = new_snapshot
        _log_scan_complete(stats)
        return stats

    known = await _load_known_paths()

    # A full rescan also re-checks the stages of unchanged photos. The stage
    # state is loaded once up front instead of queried per photo per stage.
    facts: dict[str, PhotoFacts] = {}
    outputs: StageOutputs | None = None
    if not fast:
        async with async_session() as session:
            facts = {f.file_hash: f for f in await load_photo_facts(session)}
            outputs = await load_stage_outputs(session)

    # A directory is only recorded in the snapshot when everything in it was
    # handled cleanly: a dir with errors (e.g. a file still being copied)
    # gets re-checked on the next sweep.
    cancelled = False
    error_dirs: set[str] = set()
    for i, (filepath, file_stat) in enumerate(photo_files):
        if cancel_check and cancel_check():
            logger.info("Scan cancelled by user")
            cancelled = True
            break

        rel_path = str(filepath.relative_to(photos_dir))
        unchanged_hash = _unchanged_hash(known.get(rel_path), file_stat)

        try:
            if unchanged_hash is not None:
                # Fast sweeps only look for new/changed/removed files;
                # re-queueing incomplete stages of unchanged photos is the
                # full rescan's job.
                if fast:
                    stats["skipped"] += 1
                    continue
                photo_facts = facts.get(unchanged_hash)
                stage = outputs.first_needed_stage(photo_facts) if photo_facts else None
                if stage is None:
                    stats["skipped"] += 1
                elif on_file_discovered:
                    await on_file_discovered(unchanged_hash, stage.value)
            else:
                # Validity (PIL verify) is expensive and image-only. Videos
                # can't be opened by PIL; they're validated later when their
                # poster frame is extracted.
                if not is_supported_video(filepath) and not await asyncio.to_thread(
                    is_valid_image, filepath
                ):
                    stats["errors"] += 1
                    error_dirs.add(str(filepath.parent))
                    continue

                async with _index_lock, async_session() as session:
                    entry = await _index_photo(session, filepath, stats, file_stat)
                    await session.commit()
                if entry and on_file_discovered:
                    await on_file_discovered(*entry)
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
        _seen_snapshot = seen_paths

    _log_scan_complete(stats)
    return stats


def _log_scan_complete(stats: dict) -> None:
    logger.info(
        "Scan complete: %d total, %d new, %d updated, %d skipped, %d errors",
        stats["total"],
        stats["new"],
        stats["updated"],
        stats["skipped"],
        stats["errors"],
    )


async def _entry_stage(session: AsyncSession, photo: Photo) -> str | None:
    stage = await first_needed_stage(session, photo)
    return stage.value if stage else None


async def _index_photo(
    session: AsyncSession, filepath: Path, stats: dict, file_stat: os.stat_result | None = None
) -> tuple[str, str] | None:
    """Index a single photo file. Callers hold _index_lock.

    Returns:
        (file_hash, entry_stage) if photo needs processing
        None if photo is fully processed or not indexed
    """
    relative_path = str(filepath.relative_to(settings.photos_dir))
    if file_stat is None:
        file_stat = await asyncio.to_thread(filepath.stat)
    file_size = file_stat.st_size
    file_mtime = file_stat.st_mtime

    # Already indexed at this path with the same size and mtime? A path can
    # carry more than one photo (one per content version after an in-place
    # edit), so look at all of them.
    path_hashes = (
        await session.execute(
            select(PhotoPath.file_hash).where(PhotoPath.file_path == relative_path)
        )
    ).scalars().all()
    for path_hash in path_hashes:
        existing_photo = await session.get(Photo, path_hash)
        if (
            existing_photo
            and existing_photo.file_size == file_size
            and existing_photo.file_modified
            and _mtime_equal(existing_photo.file_modified.timestamp(), file_mtime)
        ):
            # File unchanged - check if any processing is needed
            entry_stage = await _entry_stage(session, existing_photo)
            if entry_stage:
                return (path_hash, entry_stage)
            stats["skipped"] += 1
            return None

    # Compute hash
    file_hash = await asyncio.to_thread(compute_file_hash, filepath)

    # Check if photo exists by hash
    existing_by_hash = await session.get(Photo, file_hash)

    if existing_by_hash:
        # Update path if needed
        if file_hash not in path_hashes:
            session.add(PhotoPath(file_hash=file_hash, file_path=relative_path))
            old_path = settings.photos_dir / existing_by_hash.file_path
            if not old_path.exists():
                existing_by_hash.file_path = relative_path
            stats["updated"] += 1
        else:
            stats["skipped"] += 1

        # Check if processing is needed
        entry_stage = await _entry_stage(session, existing_by_hash)
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


def _removed_from_library(candidates: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Indexed paths that are gone: deleted from disk, or no longer library
    paths at all (see is_library_path)."""
    return [
        (h, p) for h, p in candidates
        if not is_library_path(p) or not (settings.photos_dir / p).exists()
    ]


async def _cleanup_removed_files(seen_paths: set[str] | None = None) -> None:
    """Remove database entries for files that no longer exist on disk, or
    that are no longer library paths (hidden or temp, see is_library_path).

    When the caller provides the set of paths seen during its walk, only the
    paths missing from that set are stat-checked: at 40k photos, exists()
    on every DB path over a Docker bind mount is far too slow.
    """
    async with async_session() as session:
        rows = (await session.execute(select(PhotoPath.file_hash, PhotoPath.file_path))).all()

    candidates = [
        (file_hash, file_path)
        for file_hash, file_path in rows
        if seen_paths is None or file_path not in seen_paths
    ]
    del rows
    if not candidates:
        return
    removed_paths = await asyncio.to_thread(_removed_from_library, candidates)
    if not removed_paths:
        return

    # Refuse to clean up when the library is *unavailable* rather than
    # emptied. Deleting here cascades to faces, captions, favourites and
    # flags, which cost days of processing to rebuild, so an unmounted or
    # unreadable directory must not be mistaken for a deletion.
    #
    # There is deliberately no cap on how many files may be cleaned up at
    # once. Deleting a big folder is a normal thing to do, and a threshold
    # would leave the index permanently unable to converge on the truth.
    # The two checks below are unambiguous failures rather than heuristics:
    # a genuine deletion leaves the library readable and still full of
    # other photos.
    if not settings.photos_dir.is_dir():
        logger.error(
            "REFUSING to clean up %d indexed paths: %s is not a readable "
            "directory. The library looks unmounted, not deleted. Nothing "
            "was removed from the index.",
            len(removed_paths), settings.photos_dir,
        )
        return
    if seen_paths is not None and not seen_paths:
        logger.error(
            "REFUSING to clean up %d indexed paths: the sweep of %s found "
            "no photos at all. The library looks unmounted or empty, not "
            "deleted. Nothing was removed from the index.",
            len(removed_paths), settings.photos_dir,
        )
        return

    async with _index_lock, async_session() as session:
        for file_hash, file_path in removed_paths:
            await session.execute(
                delete(PhotoPath).where(
                    PhotoPath.file_hash == file_hash, PhotoPath.file_path == file_path
                )
            )

        for file_hash in dict.fromkeys(h for h, _ in removed_paths):
            remaining = set(
                (
                    await session.execute(
                        select(PhotoPath.file_path).where(PhotoPath.file_hash == file_hash)
                    )
                ).scalars()
            )
            photo = await session.get(Photo, file_hash)
            if not photo:
                continue
            if not remaining:
                # ORM delete: cascades to faces, caption, tags, hashes and
                # stage failures through the Photo relationships.
                await session.delete(photo)
            elif photo.file_path not in remaining:
                # The copy the photo pointed at is gone but another remains:
                # point at that one, or originals and thumbnails would be
                # read from a path that no longer exists.
                photo.file_path = min(remaining)

        await session.commit()
    logger.info("Cleaned up %d removed file paths", len(removed_paths))


async def index_single_file(filepath: Path) -> tuple[str, str] | None:
    """Index a single newly discovered file (from file watcher).

    Returns (file_hash, entry_stage) or None if file not supported/unchanged.
    """
    if not is_supported_photo(filepath):
        return None
    try:
        relative_path = filepath.relative_to(settings.photos_dir)
    except ValueError:
        return None
    if not is_library_path(relative_path):
        return None
    if filepath.is_symlink() and not _inside_library(str(filepath), settings.photos_dir.resolve()):
        return None

    if not await asyncio.to_thread(is_valid_image, filepath):
        logger.warning("Skipping corrupted/invalid image: %s", filepath)
        return None

    try:
        stats = {"new": 0, "updated": 0, "skipped": 0, "errors": 0}
        async with _index_lock, async_session() as session:
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
