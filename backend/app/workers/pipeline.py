"""Background processing pipeline - orchestrates photo indexing and analysis.

Simplified architecture:
- Scanner discovers photos and queues them based on missing data
- Workers check if processing is needed before each stage (idempotent)
- Database and filesystem are the source of truth
- No in-memory state tracking
"""

import asyncio
import logging
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from backend.app.config import settings
from backend.app.database import async_session
from backend.app.services.scanner import index_single_file, is_supported_photo, scan_directory
from backend.app.workers.queues import QueueType, pipeline
from backend.app.workers.stages import (
    ENTRY_STAGES,
    load_photo_facts,
    load_stage_outputs,
    stage_enabled,
)

logger = logging.getLogger(__name__)

# How "Found N photos needing <stage>" names each stage in the startup log.
# The wording is relied on: after a container recreate, a huge "needing
# captioning" count is the sign that an empty index got mounted.
_STAGE_LABELS = {
    QueueType.EXIF: "EXIF extraction",
    QueueType.GEOCODING: "geocoding",
    QueueType.THUMBNAILS: "thumbnails",
    QueueType.HASHING: "hashing",
    QueueType.FACES: "face detection",
    QueueType.CAPTIONING: "captioning",
}


async def _queue_at(file_hash: str, entry_stage: str) -> None:
    """Queue a photo at the stage named by the scanner."""
    try:
        queue_type = QueueType(entry_stage)
    except ValueError:
        return
    await pipeline.add_file_at(file_hash, queue_type)
    logger.debug("Queued %s for %s", file_hash, entry_stage)


async def run_initial_scan(fast: bool = False) -> dict:
    """Run a directory scan and queue photos for processing.

    Each photo is queued for the first stage that needs processing based on:
    - Config flags (ENABLE_*)
    - Actual data/file existence

    fast=True only picks up new/changed/removed files (periodic sweep);
    fast=False also re-checks processing stages of unchanged photos.
    """

    async def progress_callback(processed: int, total: int, current_file: str):
        logger.info("Scanning: %d/%d", processed, total)

    return await scan_directory(
        progress_callback=progress_callback,
        cancel_check=lambda: pipeline._stop_requested,
        on_file_discovered=_queue_at,
        fast=fast,
    )


async def resume_incomplete_processing() -> int:
    """Queue photos that have incomplete processing based on config and actual data.

    Called on startup to resume processing after a crash or restart. Each
    photo is queued at its first needed stage only, by the same rules the
    scanner uses (stages with a recorded permanent failure are passed over);
    pipeline routing carries it through the later stages.
    Returns the number of photos queued.
    """
    async with async_session() as session:
        facts = await load_photo_facts(session)
        outputs = await load_stage_outputs(session)

    # Per-stage counts of photos still needing that stage, for the log.
    needing: dict[QueueType, int] = dict.fromkeys(ENTRY_STAGES, 0)
    by_entry: dict[QueueType, list[str]] = {}
    for f in facts:
        needed = list(outputs.needed_stages(f))
        for stage in needed:
            needing[stage] += 1
        if needed:
            by_entry.setdefault(needed[0], []).append(f.file_hash)

    for stage in ENTRY_STAGES:
        if stage_enabled(stage):
            logger.info("Found %d photos needing %s", needing[stage], _STAGE_LABELS[stage])

    failed_pairs = sum(len(stages) for stages in outputs.failures.values())
    if failed_pairs:
        logger.info("Skipping %d photo/stage pairs with recorded failures", failed_pairs)

    queued_count = 0
    for stage in ENTRY_STAGES:
        hashes = by_entry.get(stage, [])
        for file_hash in hashes:
            await pipeline.add_file_at(file_hash, stage)
        queued_count += len(hashes)
        if hashes:
            logger.info(
                "Queued %d photos at %s (earliest incomplete stage)", len(hashes), stage.value
            )

    if queued_count > 0:
        logger.info("Total: %d photos queued for processing", queued_count)
    else:
        logger.info("All photos are fully processed")

    return queued_count


class FileEventHandler(FileSystemEventHandler):
    """Debounced indexing of photos the watcher sees being written.

    A copy produces a created event and then a modified event per write, and
    sync tools (Syncthing, rsync) write a temp file and rename it into place.
    Each path is indexed once, after QUIET_SECONDS without new events for it,
    so a half-copied file is not hashed and indexed under a partial hash.
    Watchdog calls the on_* methods from its own thread.
    """

    QUIET_SECONDS = 3.0

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        self._pending: dict[Path, asyncio.TimerHandle] = {}  # touched on the loop only
        self._tasks: set[asyncio.Task] = set()

    def on_created(self, event: FileSystemEvent) -> None:
        self._touch(event, event.src_path)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._touch(event, event.src_path)

    def on_closed(self, event: FileSystemEvent) -> None:
        self._touch(event, event.src_path)

    def on_moved(self, event: FileSystemEvent) -> None:
        self._touch(event, event.dest_path)

    def _touch(self, event: FileSystemEvent, path) -> None:
        if event.is_directory or not path:
            return
        filepath = Path(path if isinstance(path, str) else path.decode())
        if is_supported_photo(filepath):
            self.loop.call_soon_threadsafe(self._schedule, filepath)

    def _schedule(self, filepath: Path) -> None:
        handle = self._pending.pop(filepath, None)
        if handle:
            handle.cancel()
        self._pending[filepath] = self.loop.call_later(
            self.QUIET_SECONDS, self._fire, filepath
        )

    def _fire(self, filepath: Path) -> None:
        self._pending.pop(filepath, None)
        task = self.loop.create_task(self._queue_file(filepath))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _queue_file(self, filepath: Path) -> None:
        if not filepath.exists():
            return  # moved on or deleted again; the sweep settles it
        result = await index_single_file(filepath)
        if result:
            file_hash, entry_stage = result
            await _queue_at(file_hash, entry_stage)
            logger.info("Indexed new file: %s (%s)", filepath, file_hash)


# True once the inotify observer is running. Note: inotify events don't cross
# Docker bind mounts on Windows/macOS hosts; there the periodic sweep is what
# actually detects changes.
watcher_active = False


async def start_file_watcher():
    """Start watching the photos directory for new files.

    Returns the observer, or None when the directory cannot be watched (the
    periodic sweep still runs).
    """
    global watcher_active
    handler = FileEventHandler(asyncio.get_running_loop())
    observer = Observer()
    try:
        observer.schedule(handler, str(settings.photos_dir), recursive=True)
        observer.start()
    except OSError as e:
        logger.error("File watcher not started for %s: %s", settings.photos_dir, e)
        return None
    watcher_active = True
    logger.info("File watcher started for %s", settings.photos_dir)
    return observer
