"""Background processing pipeline - orchestrates photo indexing and analysis."""

import asyncio
import logging
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent

from backend.app.config import settings
from backend.app.services.scanner import scan_directory, index_single_file, is_supported_photo
from backend.app.services.exif import process_pending_exif
from backend.app.services.thumbnail import process_pending_thumbnails
from backend.app.services.hasher import process_pending_hashes, find_duplicates
from backend.app.services.geocoder import process_pending_geocoding
from backend.app.services.clip_tagger import process_pending_tags
from backend.app.services.face_detector import process_pending_faces, cluster_faces
from backend.app.services.captioner import process_pending_captions
from backend.app.services.event_detector import detect_events
from backend.app.services.motion_photo import process_pending_motion_photos

logger = logging.getLogger(__name__)


class ScanState:
    """Shared scan state for progress reporting."""

    def __init__(self):
        self.is_scanning: bool = False
        self.total_files: int = 0
        self.processed_files: int = 0
        self.current_file: str | None = None
        self.phase: str | None = None
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
        }


# Global scan state
scan_state = ScanState()


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


async def run_initial_scan() -> dict:
    """Run the initial directory scan and full processing pipeline."""
    global scan_state

    scan_state.is_scanning = True
    scan_state.phase = "discovery"
    await scan_state.notify()

    async def progress_callback(processed: int, total: int, current_file: str):
        scan_state.processed_files = processed
        scan_state.total_files = total
        scan_state.current_file = current_file
        await scan_state.notify()

    try:
        stats = await scan_directory(progress_callback=progress_callback)

        # Phase 1: Core metadata extraction
        scan_state.phase = "exif"
        await scan_state.notify()
        while await process_pending_exif(batch_size=100):
            await scan_state.notify()

        # Phase 2: Geocode
        scan_state.phase = "geocoding"
        await scan_state.notify()
        await process_pending_geocoding(batch_size=100)

        # Phase 3: Generate thumbnails
        scan_state.phase = "thumbnails"
        await scan_state.notify()
        while await process_pending_thumbnails(batch_size=50):
            await scan_state.notify()

        # Phase 4: Extract motion photo videos
        scan_state.phase = "motion_photos"
        await scan_state.notify()
        await process_pending_motion_photos(batch_size=50)

        # Phase 5: Perceptual hashing + duplicate detection
        scan_state.phase = "hashing"
        await scan_state.notify()
        while await process_pending_hashes(batch_size=100):
            await scan_state.notify()
        await find_duplicates()

        # Phase 6: CLIP tagging (optional - requires ML deps)
        scan_state.phase = "clip"
        await scan_state.notify()
        try:
            while await process_pending_tags(batch_size=20):
                await scan_state.notify()
        except Exception:
            logger.info("CLIP tagging skipped or failed (ML dependencies may not be installed)")

        # Phase 7: Face detection (optional - requires ML deps)
        scan_state.phase = "faces"
        await scan_state.notify()
        try:
            while await process_pending_faces(batch_size=20):
                await scan_state.notify()
            # Cluster detected faces into persons
            await cluster_faces()
        except Exception:
            logger.info("Face detection skipped or failed (ML dependencies may not be installed)")

        # Phase 8: Ollama captioning (optional - requires running Ollama)
        scan_state.phase = "captioning"
        await scan_state.notify()
        try:
            while await process_pending_captions(batch_size=10):
                await scan_state.notify()
        except Exception:
            logger.info("Ollama captioning skipped or failed (Ollama may not be running)")

        # Phase 9: Event detection
        scan_state.phase = "events"
        await scan_state.notify()
        try:
            await detect_events()
        except Exception:
            logger.exception("Event detection failed")

        return stats

    finally:
        scan_state.is_scanning = False
        scan_state.phase = None
        scan_state.current_file = None
        await scan_state.notify()


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
    """Process file events from the watcher."""
    while True:
        try:
            filepath = await asyncio.wait_for(queue.get(), timeout=5.0)
            # Debounce: wait a moment for file to be fully written
            await asyncio.sleep(1.0)

            logger.info("Detected file change: %s", filepath)
            file_hash = await index_single_file(filepath)
            if file_hash:
                # Process the new file through the full pipeline
                from backend.app.services.exif import extract_exif
                from backend.app.services.thumbnail import generate_thumbnails
                from backend.app.services.hasher import compute_hashes
                from backend.app.services.geocoder import geocode_photo
                from backend.app.services.clip_tagger import tag_photo
                from backend.app.services.face_detector import detect_faces
                from backend.app.services.captioner import caption_photo

                await extract_exif(file_hash)
                await geocode_photo(file_hash)
                await generate_thumbnails(file_hash)
                await compute_hashes(file_hash)

                # Optional ML processing (may fail if deps not installed)
                try:
                    await tag_photo(file_hash)
                except Exception:
                    pass
                try:
                    await detect_faces(file_hash)
                except Exception:
                    pass
                try:
                    await caption_photo(file_hash)
                except Exception:
                    pass

        except asyncio.TimeoutError:
            continue
        except Exception:
            logger.exception("Error processing file event")
            await asyncio.sleep(1.0)
