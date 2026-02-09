"""Background processing pipeline - orchestrates photo indexing and analysis."""

import asyncio
import logging
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent

from backend.app.config import settings
from backend.app.services.scanner import scan_directory, index_single_file, is_supported_photo
from backend.app.workers.queues import pipeline, QueueType

logger = logging.getLogger(__name__)


class ScanState:
    """Shared scan state for progress reporting."""

    def __init__(self):
        self.is_scanning: bool = False
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


async def run_initial_scan() -> dict:
    """Run the initial directory scan and feed discovered files to the pipeline.

    This function ONLY handles scanning/discovery. The actual processing is done
    by the pipeline workers started separately via start_pipeline_workers().
    """
    global scan_state

    scan_state.is_scanning = True
    scan_state.phase = "discovery"
    scan_state.phase_progress = 0
    scan_state.phase_total = 0
    await scan_state.notify()

    async def progress_callback(processed: int, total: int, current_file: str):
        scan_state.processed_files = processed
        scan_state.total_files = total
        scan_state.current_file = current_file
        scan_state.phase_progress = processed
        scan_state.phase_total = max(total, 1)
        await scan_state.notify()

    try:
        stats = await scan_directory(progress_callback=progress_callback)

        # Add only NEW files to the pipeline
        discovered = stats.get("discovered_files", {})
        logger.info("Feeding %d discovered files to pipeline", len(discovered))
        for file_hash, file_path in discovered.items():
            await pipeline.add_file(file_hash, file_path)

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
