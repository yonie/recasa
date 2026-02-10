"""Background processing pipeline - orchestrates photo indexing and analysis."""

import asyncio
import logging
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent

from sqlalchemy import select, or_

from backend.app.config import settings
from backend.app.database import async_session
from backend.app.models import Photo
from backend.app.services.scanner import scan_directory, index_single_file, is_supported_photo
from backend.app.workers.queues import pipeline, QueueType, QueueStats

logger = logging.getLogger(__name__)


class ScanState:
    """Shared scan state for progress reporting."""

    def __init__(self):
        self.is_scanning: bool = False
        self.cancel_requested: bool = False
        self.total_files: int = 0
        self.processed_files: int = 0
        self.current_file: str | None = None
        self.phase: str | None = None
        self.phase_progress: int = 0
        self.phase_total: int = 0
        self._listeners: list[asyncio.Queue] = []

    def add_listener(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._listeners.append(queue)
        return queue

    def remove_listener(self, queue: asyncio.Queue) -> None:
        if queue in self._listeners:
            self._listeners.remove(queue)

    async def notify(self) -> None:
        msg = {
            "is_scanning": self.is_scanning,
            "total_files": self.total_files,
            "processed_files": self.processed_files,
            "current_file": self.current_file,
            "phase": self.phase,
            "phase_progress": self.phase_progress,
            "phase_total": self.phase_total,
        }
        for queue in self._listeners:
            try:
                queue.put_nowait(msg)
            except asyncio.QueueFull:
                pass

    def to_dict(self) -> dict:
        return {
            "is_scanning": self.is_scanning,
            "total_files": self.total_files,
            "processed_files": self.processed_files,
            "current_file": self.current_file,
            "phase": self.phase,
            "phase_progress": self.phase_progress,
            "phase_total": self.phase_total,
        }


# Global scan state
scan_state = ScanState()

# Batch size for resuming incomplete files (keep small to limit memory)
_RESUME_BATCH_SIZE = 50


async def _resume_incomplete_files() -> int:
    """Find photos that are indexed but not fully processed and feed them to the pipeline.

    Queries the DB for photos missing at least one processing flag, then feeds
    them to the pipeline in small batches so memory usage stays bounded.
    Returns the number of files resumed.
    """
    async with async_session() as session:
        result = await session.execute(
            select(Photo.file_hash, Photo.file_path).where(
                or_(
                    Photo.exif_extracted == False,  # noqa: E712
                    Photo.thumbnail_generated == False,  # noqa: E712
                    Photo.perceptual_hashed == False,  # noqa: E712
                    Photo.faces_detected == False,  # noqa: E712
                    Photo.ollama_captioned == False,  # noqa: E712
                )
            )
        )
        incomplete = result.all()

    if not incomplete:
        return 0

    resumed = 0
    for i in range(0, len(incomplete), _RESUME_BATCH_SIZE):
        batch = incomplete[i : i + _RESUME_BATCH_SIZE]
        for file_hash, file_path in batch:
            # Skip files already known to the pipeline in this session
            if pipeline.queues[QueueType.DISCOVERY].is_queued(file_hash):
                continue
            full_path = settings.photos_dir / file_path
            if full_path.exists():
                await pipeline.add_file(file_hash, str(full_path))
                resumed += 1
        # Yield to the event loop between batches so workers can make progress
        # and free memory before we enqueue more
        await asyncio.sleep(0.5)

    return resumed


async def run_initial_scan() -> dict:
    """Run the initial directory scan and feed discovered files to the pipeline.

    This function ONLY handles scanning/discovery. The actual processing is done
    by the pipeline workers started separately via start_pipeline_workers().
    """
    global scan_state

    scan_state.is_scanning = True
    scan_state.cancel_requested = False
    scan_state.phase = "discovery"
    scan_state.phase_progress = 0
    scan_state.phase_total = 0

    # Reset pipeline counters and tracking sets for a fresh scan.
    # Each worker stage checks DB flags before doing actual work, so
    # clearing _processed is safe — it just means a file might enter
    # the queue again, but the worker will skip it after the DB check.
    pipeline._total_discovered = 0
    pipeline._completed_time = None
    for qtype in QueueType:
        q = pipeline.queues[qtype]
        q._processed.clear()
        q._processing.clear()
        q.stats = QueueStats(queue_type=qtype)

    await scan_state.notify()

    async def progress_callback(processed: int, total: int, current_file: str):
        scan_state.processed_files = processed
        scan_state.total_files = total
        scan_state.current_file = current_file
        scan_state.phase_progress = processed
        scan_state.phase_total = max(total, 1)
        await scan_state.notify()

    try:
        async def on_file_discovered(file_hash: str, file_path: str):
            """Feed files to the pipeline as soon as they are indexed."""
            await pipeline.add_file(file_hash, file_path)

        stats = await scan_directory(
            progress_callback=progress_callback,
            cancel_check=lambda: scan_state.cancel_requested,
            on_file_discovered=on_file_discovered,
        )

        discovered = stats.get("discovered_files", {})
        logger.info("Scan complete: %d new/updated files fed to pipeline", len(discovered))

        # Resume partially-processed files that weren't picked up by the scan
        # (e.g. files indexed in a prior run but not fully processed).
        # Feed them in small batches to avoid overwhelming memory.
        resumed = await _resume_incomplete_files()
        if resumed:
            logger.info("Resumed %d partially-processed files", resumed)

        return stats

    finally:
        scan_state.is_scanning = False
        scan_state.phase = None
        scan_state.current_file = None
        scan_state.phase_progress = 0
        scan_state.phase_total = 0
        await scan_state.notify()


class PhotoFileHandler(FileSystemEventHandler):
    """Watchdog handler for file system events."""

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._pending: asyncio.Queue = asyncio.Queue()

    def on_created(self, event):
        if isinstance(event, FileCreatedEvent) and not event.is_directory:
            filepath = Path(event.src_path)
            if is_supported_photo(filepath):
                asyncio.run_coroutine_threadsafe(
                    self._pending.put(filepath), self._loop
                )

    def on_modified(self, event):
        if isinstance(event, FileModifiedEvent) and not event.is_directory:
            filepath = Path(event.src_path)
            if is_supported_photo(filepath):
                asyncio.run_coroutine_threadsafe(
                    self._pending.put(filepath), self._loop
                )


async def start_file_watcher() -> Observer | None:
    """Start the filesystem watcher for detecting new/changed photos."""
    photos_dir = settings.photos_dir
    if not photos_dir.exists():
        logger.error("Photos directory does not exist: %s", photos_dir)
        return None

    loop = asyncio.get_event_loop()
    handler = PhotoFileHandler(loop)

    observer = Observer()
    observer.schedule(handler, str(photos_dir), recursive=True)
    observer.daemon = True
    observer.start()

    logger.info("File watcher started for %s", photos_dir)

    # Start background task to process file events
    asyncio.create_task(_process_file_events(handler._pending))

    return observer


async def _process_file_events(queue: asyncio.Queue) -> None:
    """Process file events from the watcher by feeding them into the pipeline."""
    while True:
        try:
            filepath = await asyncio.wait_for(queue.get(), timeout=5.0)
            # Debounce: wait a moment for file to be fully written
            await asyncio.sleep(1.0)

            logger.info("Detected file change: %s", filepath)
            file_hash = await index_single_file(filepath)
            if file_hash:
                # Feed into the pipeline -- workers handle the rest
                await pipeline.add_file(file_hash, str(filepath))

        except asyncio.TimeoutError:
            continue
        except Exception:
            logger.exception("Error processing file event")
            await asyncio.sleep(1.0)
