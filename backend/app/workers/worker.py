"""Pipeline workers for parallel photo processing.

Simplified architecture:
- Workers check if processing is needed by looking at actual data existence
  (the rules live in workers/stages.py, shared with the scanner and resume)
- No in-memory counters or _processed sets
- Config flags control whether each stage runs
"""

import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from backend.app.config import ignored_stage_switches, settings
from backend.app.database import async_session
from backend.app.exceptions import PermanentStageError
from backend.app.models import Photo, StageFailure
from backend.app.services.captioner import caption_photo
from backend.app.services.event_detector import detect_events
from backend.app.services.exif import extract_exif
from backend.app.services.face_detector import cluster_faces, detect_faces
from backend.app.services.geocoder import geocode_photo
from backend.app.services.hasher import compute_hashes, find_duplicates, phash_signature
from backend.app.services.motion_photo import extract_motion_video
from backend.app.services.thumbnail import generate_thumbnails
from backend.app.services.user_data import (
    apply_pending_hidden_group_imports,
    apply_pending_person_imports,
)
from backend.app.workers.queues import Pipeline, QueueType
from backend.app.workers.stages import (
    failure_recorded,
    has_coordinates,
    has_output,
    stage_applies,
    stage_enabled,
)

logger = logging.getLogger(__name__)

# In-memory log storage for recent pipeline activity (served by
# /api/pipeline/logs).
pipeline_logs: deque = deque(maxlen=500)


class PipelineLogHandler(logging.Handler):
    """Capture INFO+ records from the workers and services for the status page."""

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.INFO:
            return
        msg = record.getMessage()
        # Progress lines are cumulative counters, not events worth listing.
        if "Progress:" in msg:
            return
        pipeline_logs.append({
            "timestamp": datetime.now(UTC).replace(tzinfo=None).isoformat(),
            "level": record.levelname,
            "message": msg,
        })


pipeline_handler = PipelineLogHandler()
pipeline_handler.setLevel(logging.INFO)
logging.getLogger("backend.app.workers").addHandler(pipeline_handler)
logging.getLogger("backend.app.services").addHandler(pipeline_handler)

processing_semaphore: asyncio.Semaphore | None = None

# The event loop only holds weak references to tasks; keep the worker loops
# alive explicitly.
_worker_tasks: set[asyncio.Task] = set()


def get_processing_semaphore() -> asyncio.Semaphore:
    """Get or create the global processing semaphore."""
    global processing_semaphore
    if processing_semaphore is None:
        processing_semaphore = asyncio.Semaphore(settings.max_concurrent)
        logger.info("Created processing semaphore with limit: %d", settings.max_concurrent)
    return processing_semaphore


# The service that produces each stage's output, and the short name used in
# log lines ("[motion] Processing: ...").
STAGE_SERVICES: dict[QueueType, tuple[str, Callable[[str], Awaitable[object]]]] = {
    QueueType.EXIF: ("exif", extract_exif),
    QueueType.GEOCODING: ("geocoding", geocode_photo),
    QueueType.THUMBNAILS: ("thumbnails", generate_thumbnails),
    QueueType.MOTION_PHOTOS: ("motion", extract_motion_video),
    QueueType.HASHING: ("hashing", compute_hashes),
    QueueType.FACES: ("faces", detect_faces),
    QueueType.CAPTIONING: ("captioning", caption_photo),
}

PROGRESS_EVERY = 100


class Worker:
    """Worker that processes files from one stage's queue."""

    def __init__(self, pipeline: Pipeline, queue_type: QueueType, worker_id: int = 0):
        self.pipeline = pipeline
        self.queue_type = queue_type
        self.worker_id = worker_id
        self.queue = pipeline.queues[queue_type]
        self._running = False
        self._processed = 0  # for the periodic progress line only

    def _log_error(self, file_hash: str, file_path: str | None, error: str) -> None:
        self.pipeline.add_error(
            queue=self.queue_type.value,
            file_hash=file_hash,
            file_path=file_path,
            error=error,
        )

    async def _record_failure(self, file_hash: str, error: str) -> None:
        """Persist a stage failure so scans stop re-queueing this photo forever."""
        try:
            async with async_session() as session:
                await session.merge(
                    StageFailure(
                        file_hash=file_hash,
                        stage=self.queue_type.value,
                        error=error,
                        failed_at=datetime.now(),
                    )
                )
                await session.commit()
        except Exception as e:
            # Losing the record only means the photo is retried later.
            logger.warning("Could not record stage failure: %s", type(e).__name__)

    async def _should_run(self, file_hash: str) -> tuple[bool, Photo | None]:
        """Decide whether this stage has work to do for the photo.

        Returns (run, photo). photo is None when the photo is gone from the
        index; such an item is dropped rather than routed on.
        """
        async with async_session() as session:
            photo = await session.get(Photo, file_hash)
            if photo is None:
                return False, None
            stage = self.queue_type
            run = (
                stage_applies(stage, is_video=bool(photo.is_video),
                              has_gps=has_coordinates(photo))
                and not await has_output(session, stage, photo)
                # A photo can reach a stage that already failed for it by being
                # routed through from an earlier one; retrying would just fail
                # again. A stage rebuild (clear-stage) clears the record.
                and not await failure_recorded(session, stage, file_hash)
            )
            return run, photo

    async def process_item(self, file_hash: str) -> bool:
        """Process a single item through this worker's stage."""
        entry = STAGE_SERVICES.get(self.queue_type)
        if entry is None:
            return False
        name, service_fn = entry
        # A Stop while this item is in hand ends its trip after this stage.
        generation = self.pipeline.generation

        if not stage_enabled(self.queue_type):
            await self.pipeline.route_to_next(file_hash, self.queue_type, generation)
            return True

        run, photo = await self._should_run(file_hash)
        if photo is None:
            self._log_error(file_hash, None, "Photo not found in database")
            return False
        if not run:
            logger.debug("[%s] Skip: %s", name, photo.file_path)
            await self.pipeline.route_to_next(file_hash, self.queue_type, generation)
            return True

        filepath = str(settings.photos_dir / photo.file_path)
        self.queue.current_file_hash = file_hash
        self.queue.current_file_path = filepath
        logger.info("[%s] Processing: %s", name, photo.file_path)

        try:
            await service_fn(file_hash)
            logger.info("[%s] Done: %s", name, photo.file_path)
        except PermanentStageError as e:
            logger.warning("[%s] Unreadable: %s - %s", name, photo.file_path, e)
            self._log_error(file_hash, filepath, str(e)[:100])
            await self._record_failure(file_hash, str(e)[:200])
        except Exception as e:
            # Transient (service/network) errors are not persisted: the photo
            # will be retried by a later scan.
            logger.warning("[%s] Failed: %s - %s", name, photo.file_path, type(e).__name__)
            self._log_error(file_hash, filepath, str(e)[:100])
        finally:
            self.queue.current_file_hash = None
            self.queue.current_file_path = None

        await self.pipeline.route_to_next(file_hash, self.queue_type, generation)
        self._log_progress()
        return True

    def _log_progress(self) -> None:
        self._processed += 1
        if self._processed % PROGRESS_EVERY == 0:
            logger.info(
                "[%s] Progress: %d processed, %d pending",
                self.queue_type.value, self._processed, self.queue.qsize(),
            )

    async def run(self) -> None:
        """Run the worker loop."""
        self._running = True
        semaphore = get_processing_semaphore()
        logger.info("Worker %d started for queue %s", self.worker_id, self.queue_type.value)

        # A Stop drains the queues but does not end this loop: Resume and
        # later scans need the workers again.
        while self._running:
            try:
                file_hash = await asyncio.wait_for(self.queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            generation = self.pipeline.generation
            try:
                async with semaphore:
                    if generation != self.pipeline.generation:
                        continue  # stopped while waiting for a slot
                    await self.process_item(file_hash)
            except Exception as e:
                # One bad item must not end the worker loop.
                logger.warning(
                    "Worker %d error (%s): %s", self.worker_id, self.queue_type.value,
                    type(e).__name__,
                )
                await asyncio.sleep(0.5)

        logger.info("Worker %d stopped for queue %s", self.worker_id, self.queue_type.value)

    def stop(self) -> None:
        self._running = False


class EventDetectionWorker:
    """Runs face clustering, duplicate and event detection in batches.

    Every photo leaving the last stage lands in the EVENTS queue; this worker
    drains it, waits for upstream to settle, then recomputes the library-wide
    results once per batch.
    """

    MIN_EVENT_INTERVAL = 60.0  # seconds between event detections
    SETTLE_SECONDS = 5

    def __init__(self, pipeline: Pipeline):
        self.pipeline = pipeline
        self._running = False
        self._last_event_run = 0.0
        # A batch skipped event detection inside MIN_EVENT_INTERVAL; it runs
        # once the interval has passed, even if no further photo arrives.
        self._events_pending = False
        # Perceptual-hash input of the last duplicate detection; when it has
        # not changed the stored groups are already exactly what a rerun
        # would write.
        self._last_phash_signature: bytes | None = None

    async def run(self) -> None:
        self._running = True
        logger.info("Event detection worker started")
        events_queue = self.pipeline.queues[QueueType.EVENTS]

        while self._running:
            while events_queue.empty() and self._running:
                if self._events_pending and self._events_due():
                    await self._detect_events()
                await asyncio.sleep(2)
            if not self._running:
                break

            drained = events_queue.drain()
            if drained == 0:
                continue
            logger.debug("Event worker: drained %d items", drained)

            await asyncio.sleep(self.SETTLE_SECONDS)
            await self._run_batch()

        logger.info("Event detection worker stopped")

    async def _run_batch(self) -> None:
        if settings.ENABLE_FACE_DETECTION:
            logger.debug("Running batch face clustering...")
            await _guarded("Face clustering", cluster_faces)
            # Person names and hidden Together tiles from an Export/Import wait
            # for clustering to produce persons they can match.
            await _guarded("Pending person import", apply_pending_person_imports)
            await _guarded("Pending hidden-group import", apply_pending_hidden_group_imports)

        await self._detect_duplicates()

        if self._events_due():
            await self._detect_events()
        else:
            logger.debug("Deferring event detection (debounced)")
            self._events_pending = True

    def _events_due(self) -> bool:
        return time.time() - self._last_event_run >= self.MIN_EVENT_INTERVAL

    async def _detect_events(self) -> None:
        now = time.time()
        logger.info("Running batch event detection...")
        self._events_pending = False
        if await _guarded("Event detection", detect_events):
            self._last_event_run = now

    async def _detect_duplicates(self) -> None:
        try:
            signature = await phash_signature()
        except Exception as e:
            logger.warning("Duplicate detection failed: %s", type(e).__name__)
            return
        if signature == self._last_phash_signature:
            logger.debug("Skipping duplicate detection (perceptual hashes unchanged)")
            return
        logger.info("Running batch duplicate detection...")
        if await _guarded("Duplicate detection", find_duplicates):
            self._last_phash_signature = signature

    def stop(self) -> None:
        self._running = False


async def _guarded(what: str, fn: Callable[[], Awaitable[object]]) -> bool:
    """Run a batch step; log and swallow its failure so the next step still runs."""
    try:
        await fn()
        return True
    except Exception as e:
        logger.warning("%s failed: %s", what, type(e).__name__)
        return False


async def start_pipeline_workers(pipeline: Pipeline) -> list[Worker]:
    """Start one worker per stage queue plus the batch event worker."""
    for switch in ignored_stage_switches():
        logger.warning(
            "%s is set but is not a setting: that stage always runs. Only "
            "ENABLE_GEOCODING, ENABLE_FACE_DETECTION and ENABLE_CAPTIONING switch "
            "stages off.", switch,
        )

    workers = []
    for queue_type in STAGE_SERVICES:
        worker = Worker(pipeline, queue_type, worker_id=len(workers))
        _worker_tasks.add(asyncio.create_task(worker.run()))
        workers.append(worker)

    event_worker = EventDetectionWorker(pipeline)
    _worker_tasks.add(asyncio.create_task(event_worker.run()))

    pipeline.is_running = True
    logger.info("Started %d pipeline workers", len(workers))
    return workers
