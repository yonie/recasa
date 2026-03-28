"""Pipeline workers for parallel photo processing.

Simplified architecture:
- Workers check if processing is needed by looking at actual data existence
- No in-memory counters or _processed sets
- Config flags control whether each stage runs
- Stage handlers are driven by a config table, not individual methods
"""

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select, func

from backend.app.config import settings
from backend.app.database import async_session
from backend.app.models import Photo, PhotoHash, Face, Caption
from backend.app.services.exif import extract_exif
from backend.app.services.thumbnail import generate_thumbnails
from backend.app.services.hasher import compute_hashes
from backend.app.services.geocoder import geocode_photo
from backend.app.services.face_detector import detect_faces, cluster_faces
from backend.app.services.captioner import caption_photo
from backend.app.services.event_detector import detect_events
from backend.app.services.motion_photo import extract_motion_video
from backend.app.services.scanner import thumb_exists
from backend.app.workers.queues import Pipeline, QueueType

logger = logging.getLogger(__name__)

# In-memory log storage for recent pipeline activity
pipeline_logs: deque = deque(maxlen=500)

class PipelineLogHandler(logging.Handler):
    """Custom handler to capture pipeline logs."""

    def emit(self, record: logging.LogRecord) -> None:
        # Only capture pipeline worker logs
        if record.name.startswith('backend.app.workers') or record.name.startswith('backend.app.services'):
            # Only INFO level or higher, skip progress spam
            if record.levelno >= logging.INFO:
                msg = record.getMessage()
                # Skip progress messages (they're for cumulative tracking)
                if 'Progress:' not in msg:
                    pipeline_logs.append({
                        'timestamp': datetime.utcnow().isoformat(),
                        'level': record.levelname,
                        'message': msg,
                    })

# Install the handler
pipeline_handler = PipelineLogHandler()
pipeline_handler.setLevel(logging.INFO)
logging.getLogger('backend.app.workers').addHandler(pipeline_handler)
logging.getLogger('backend.app.services').addHandler(pipeline_handler)

processing_semaphore: asyncio.Semaphore | None = None


def get_processing_semaphore() -> asyncio.Semaphore:
    """Get or create the global processing semaphore."""
    global processing_semaphore
    if processing_semaphore is None:
        processing_semaphore = asyncio.Semaphore(settings.max_concurrent)
        logger.info(f"Created processing semaphore with limit: {settings.max_concurrent}")
    return processing_semaphore


# --- Stage configuration ---

@dataclass
class StageConfig:
    """Configuration for a pipeline processing stage."""
    name: str
    queue_type: QueueType
    enabled: Callable[[], bool]
    is_done: Callable[["Worker", Photo, str], Awaitable[bool] | bool]
    service_fn: Callable[[str], Awaitable[object]]
    skip_if: Callable[["Worker", Photo, str], bool] | None = None


async def _exif_is_done(worker: "Worker", photo: Photo, file_hash: str) -> bool:
    return photo.camera_make is not None or photo.date_taken is not None

async def _geocoding_is_done(worker: "Worker", photo: Photo, file_hash: str) -> bool:
    return photo.location_city is not None

def _geocoding_skip_if(worker: "Worker", photo: Photo, file_hash: str) -> bool:
    return photo.gps_latitude is None

async def _thumbnails_is_done(worker: "Worker", photo: Photo, file_hash: str) -> bool:
    return thumb_exists(file_hash)

async def _hashing_is_done(worker: "Worker", photo: Photo, file_hash: str) -> bool:
    async with async_session() as session:
        result = await session.execute(
            select(PhotoHash).where(PhotoHash.file_hash == file_hash)
        )
        return result.scalar_one_or_none() is not None

async def _faces_is_done(worker: "Worker", photo: Photo, file_hash: str) -> bool:
    async with async_session() as session:
        result = await session.execute(
            select(func.count(Face.file_hash)).where(Face.file_hash == file_hash)
        )
        return (result.scalar() or 0) > 0

async def _caption_is_done(worker: "Worker", photo: Photo, file_hash: str) -> bool:
    async with async_session() as session:
        result = await session.execute(
            select(Caption).where(Caption.file_hash == file_hash)
        )
        return result.scalar_one_or_none() is not None

# Motion photos have no idempotency check -- always run (fast no-op if not a motion photo)
async def _motion_never_done(worker: "Worker", photo: Photo, file_hash: str) -> bool:
    return False


STAGE_CONFIGS: dict[QueueType, StageConfig] = {
    QueueType.EXIF: StageConfig(
        name="exif",
        queue_type=QueueType.EXIF,
        enabled=lambda: True,
        is_done=_exif_is_done,
        service_fn=extract_exif,
    ),
    QueueType.GEOCODING: StageConfig(
        name="geocoding",
        queue_type=QueueType.GEOCODING,
        enabled=lambda: settings.ENABLE_GEOCODING,
        is_done=_geocoding_is_done,
        skip_if=_geocoding_skip_if,
        service_fn=geocode_photo,
    ),
    QueueType.THUMBNAILS: StageConfig(
        name="thumbnails",
        queue_type=QueueType.THUMBNAILS,
        enabled=lambda: True,
        is_done=_thumbnails_is_done,
        service_fn=generate_thumbnails,
    ),
    QueueType.MOTION_PHOTOS: StageConfig(
        name="motion",
        queue_type=QueueType.MOTION_PHOTOS,
        enabled=lambda: True,
        is_done=_motion_never_done,
        service_fn=extract_motion_video,
    ),
    QueueType.HASHING: StageConfig(
        name="hashing",
        queue_type=QueueType.HASHING,
        enabled=lambda: True,
        is_done=_hashing_is_done,
        service_fn=compute_hashes,
    ),
    QueueType.FACES: StageConfig(
        name="faces",
        queue_type=QueueType.FACES,
        enabled=lambda: settings.ENABLE_FACE_DETECTION,
        is_done=_faces_is_done,
        service_fn=detect_faces,
    ),
    QueueType.CAPTIONING: StageConfig(
        name="captioning",
        queue_type=QueueType.CAPTIONING,
        enabled=lambda: settings.ENABLE_CAPTIONING,
        is_done=_caption_is_done,
        service_fn=caption_photo,
    ),
}


class Worker:
    """Worker that processes files from a specific queue.

    Uses STAGE_CONFIGS to drive a generic processing loop rather than
    per-stage handler methods.
    """

    # Progress tracking - shared across all worker instances for each queue type
    _progress_counts: dict[str, int] = {}
    _progress_logs: dict[str, int] = {}

    def __init__(self, pipeline: Pipeline, queue_type: QueueType, worker_id: int = 0):
        self.pipeline = pipeline
        self.queue_type = queue_type
        self.worker_id = worker_id
        self.queue = pipeline.queues[queue_type]
        self._running = False

    def _log_error(self, file_hash: str, file_path: str | None, error: str):
        """Log an error."""
        self.pipeline.add_error(
            queue=self.queue_type.value,
            file_hash=file_hash,
            file_path=file_path,
            error=error,
        )

    async def process_item(self, file_hash: str) -> bool:
        """Process a single item through the configured stage."""
        # Events queue is handled by EventDetectionWorker, not here
        if self.queue_type == QueueType.EVENTS:
            return True

        config = STAGE_CONFIGS.get(self.queue_type)
        if not config:
            return False

        # Stage disabled -- skip to next
        if not config.enabled():
            await self.pipeline.route_to_next(file_hash, self.queue_type)
            return True

        # Get photo from DB
        async with async_session() as session:
            photo = await session.get(Photo, file_hash)
        if not photo:
            self._log_error(file_hash, None, "Photo not found in database")
            return False

        filepath = settings.photos_dir / photo.file_path

        # Skip if condition met (e.g., no GPS data for geocoding)
        if config.skip_if and config.skip_if(self, photo, file_hash):
            logger.debug(f"[{config.name}] Skip: {photo.file_path}")
            await self.pipeline.route_to_next(file_hash, self.queue_type)
            return True

        # Already processed -- skip
        done = config.is_done(self, photo, file_hash)
        if asyncio.iscoroutine(done):
            done = await done
        if done:
            logger.debug(f"[{config.name}] Skip: {photo.file_path} (already done)")
            await self.pipeline.route_to_next(file_hash, self.queue_type)
            return True

        # Process
        self.queue.current_file_hash = file_hash
        self.queue.current_file_path = str(filepath)
        logger.info(f"[{config.name}] Processing: {photo.file_path}")

        try:
            result = await config.service_fn(file_hash)
            logger.info(f"[{config.name}] Done: {photo.file_path}")
        except Exception as e:
            logger.warning(f"[{config.name}] Failed: {photo.file_path} - {type(e).__name__}")
            self._log_error(file_hash, str(filepath), str(e)[:100])

        self.queue.current_file_hash = None
        self.queue.current_file_path = None
        await self.pipeline.route_to_next(file_hash, self.queue_type)

        self._log_progress()
        return True

    def _log_progress(self):
        """Log progress every 100 items."""
        queue_name = self.queue_type.value
        if queue_name not in Worker._progress_counts:
            Worker._progress_counts[queue_name] = 0
            Worker._progress_logs[queue_name] = 0

        Worker._progress_counts[queue_name] += 1
        count = Worker._progress_counts[queue_name]
        last_milestone = Worker._progress_logs[queue_name]

        if count >= last_milestone + 100:
            Worker._progress_logs[queue_name] = (count // 100) * 100
            pending = self.queue.qsize()
            logger.info(f"[{queue_name}] Progress: {count} processed, {pending} pending")

    async def run(self):
        """Run the worker loop."""
        self._running = True
        semaphore = get_processing_semaphore()
        logger.info(f"Worker {self.worker_id} started for queue {self.queue_type.value}")

        while self._running:
            if self.pipeline._stop_requested:
                logger.info(f"Worker {self.worker_id} stopping (stop requested)")
                break
            try:
                file_hash = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                if self.pipeline._stop_requested:
                    break
                async with semaphore:
                    await self.process_item(file_hash)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.warning(f"Worker {self.worker_id} error ({self.queue_type.value}): {type(e).__name__}")
                await asyncio.sleep(0.5)

        logger.info(f"Worker {self.worker_id} stopped for queue {self.queue_type.value}")

    def stop(self):
        """Stop the worker."""
        self._running = False


class EventDetectionWorker:
    """Special worker that runs face clustering + event detection in batch."""

    def __init__(self, pipeline: Pipeline):
        self.pipeline = pipeline
        self._running = False
        self._last_event_run: float = 0
        self._min_event_interval: float = 60.0

    async def run(self):
        """Run the event detection worker."""
        import time
        self._running = True
        logger.info("Event detection worker started")

        while self._running:
            if self.pipeline._stop_requested:
                break

            events_queue = self.pipeline.queues[QueueType.EVENTS]

            # Wait for items
            while events_queue.empty() and self._running and not self.pipeline._stop_requested:
                await asyncio.sleep(2)

            if not self._running or self.pipeline._stop_requested:
                break

            # Drain queue
            drained = 0
            while not events_queue.empty():
                try:
                    await events_queue.get()
                    drained += 1
                except Exception:
                    break

            if drained == 0:
                continue

            logger.debug(f"Event worker: drained {drained} items")

            # Wait for upstream to settle
            await asyncio.sleep(5)

            # Face clustering
            if settings.ENABLE_FACE_DETECTION:
                logger.debug("Running batch face clustering...")
                try:
                    await cluster_faces()
                except Exception as e:
                    logger.warning(f"Face clustering failed: {type(e).__name__}")

            # Event detection - debounced
            now = time.time()
            if now - self._last_event_run >= self._min_event_interval:
                logger.info("Running batch event detection...")
                try:
                    await detect_events()
                    self._last_event_run = now
                except Exception as e:
                    logger.warning(f"Event detection failed: {type(e).__name__}")
            else:
                logger.debug("Skipping event detection (debounced)")

        logger.info("Event detection worker stopped")

    def stop(self):
        """Stop the worker."""
        self._running = False


async def start_pipeline_workers(pipeline: Pipeline) -> list[Worker]:
    """Start workers for all queues."""
    workers = []

    for queue_type in QueueType:
        if queue_type == QueueType.EVENTS:
            continue

        worker = Worker(pipeline, queue_type, worker_id=len(workers))
        asyncio.create_task(worker.run())
        workers.append(worker)

    event_worker = EventDetectionWorker(pipeline)
    asyncio.create_task(event_worker.run())

    pipeline.is_running = True

    logger.info(f"Started {len(workers)} pipeline workers")
    return workers


async def stop_pipeline_workers(workers: list[Worker]):
    """Stop all pipeline workers."""
    for worker in workers:
        worker.stop()

    await asyncio.sleep(1)
    logger.info("All pipeline workers stopped")
