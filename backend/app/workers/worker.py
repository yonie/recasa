"""Pipeline workers for parallel photo processing.

Simplified architecture:
- Workers check if processing is needed by looking at actual data existence
- No in-memory counters or _processed sets
- Config flags control whether each stage runs
"""

import asyncio
import logging
from collections import deque
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


class Worker:
    """Worker that processes files from a specific queue."""

    # Progress tracking - shared across all worker instances for each queue type
    _progress_counts: dict[str, int] = {}
    _progress_logs: dict[str, int] = {}  # Track last logged milestone

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

    async def _get_photo(self, file_hash: str) -> Photo | None:
        """Get photo from database."""
        async with async_session() as session:
            return await session.get(Photo, file_hash)

    async def _has_photo_hash(self, file_hash: str) -> bool:
        """Check if perceptual hash exists in database."""
        async with async_session() as session:
            result = await session.execute(
                select(PhotoHash).where(PhotoHash.file_hash == file_hash)
            )
            return result.scalar_one_or_none() is not None

    async def _has_faces(self, file_hash: str) -> bool:
        """Check if faces exist in database."""
        async with async_session() as session:
            result = await session.execute(
                select(func.count(Face.file_hash)).where(Face.file_hash == file_hash)
            )
            return (result.scalar() or 0) > 0

    async def _has_caption(self, file_hash: str) -> bool:
        """Check if caption exists in database."""
        async with async_session() as session:
            result = await session.execute(
                select(Caption).where(Caption.file_hash == file_hash)
            )
            return result.scalar_one_or_none() is not None

    def _exif_exists(self, photo: Photo) -> bool:
        """Check if EXIF data exists (camera_make OR date_taken)."""
        return photo.camera_make is not None or photo.date_taken is not None

    async def _process_exif(self, file_hash: str) -> bool:
        """Process EXIF extraction stage."""
        # EXIF is always enabled - core functionality
        
        photo = await self._get_photo(file_hash)
        if not photo:
            self._log_error(file_hash, None, "Photo not found in database")
            return False

        filepath = settings.photos_dir / photo.file_path

        if self._exif_exists(photo):
            logger.debug(f"[exif] Skip: {photo.file_path} (already extracted)")
            await self.pipeline.route_to_next(file_hash, QueueType.EXIF)
            return True

        self.queue.current_file_hash = file_hash
        self.queue.current_file_path = str(filepath)
        logger.info(f"[exif] Processing: {photo.file_path}")

        try:
            success = await extract_exif(file_hash)
            if success:
                logger.info(f"[exif] Done: {photo.file_path}")
            else:
                self._log_error(file_hash, str(filepath), "EXIF extraction failed")
                logger.warning(f"[exif] Failed: {photo.file_path}")
        except Exception as e:
            logger.warning(f"[exif] Failed: {photo.file_path} - {type(e).__name__}")
            self._log_error(file_hash, str(filepath), str(e)[:100])

        self.queue.current_file_hash = None
        self.queue.current_file_path = None
        await self.pipeline.route_to_next(file_hash, QueueType.EXIF)
        return True

    async def _process_geocoding(self, file_hash: str) -> bool:
        """Process geocoding stage."""
        if not settings.ENABLE_GEOCODING:
            await self.pipeline.route_to_next(file_hash, QueueType.GEOCODING)
            return True

        photo = await self._get_photo(file_hash)
        if not photo:
            return False

        filepath = settings.photos_dir / photo.file_path

        if photo.location_city is not None:
            logger.debug(f"[geocoding] Skip: {photo.file_path} (already geocoded: {photo.location_city})")
            await self.pipeline.route_to_next(file_hash, QueueType.GEOCODING)
            return True

        if photo.gps_latitude is None:
            logger.debug(f"[geocoding] Skip: {photo.file_path} (no GPS data)")
            await self.pipeline.route_to_next(file_hash, QueueType.GEOCODING)
            return True

        logger.info(f"[geocoding] Processing: {photo.file_path}")
        self.queue.current_file_hash = file_hash
        self.queue.current_file_path = str(filepath)

        try:
            await geocode_photo(file_hash)
            # Refresh to get updated location
            async with async_session() as session:
                updated = await session.get(Photo, file_hash)
                if updated and updated.location_city:
                    logger.info(f"[geocoding] Done: {photo.file_path} -> {updated.location_city}, {updated.location_city}")
                else:
                    logger.info(f"[geocoding] Done: {photo.file_path} (no location found)")
        except Exception as e:
            logger.warning(f"[geocoding] Failed: {photo.file_path} - {e}")

        self.queue.current_file_hash = None
        self.queue.current_file_path = None
        await self.pipeline.route_to_next(file_hash, QueueType.GEOCODING)
        return True

    async def _process_thumbnails(self, file_hash: str) -> bool:
        """Process thumbnail generation stage."""
        # Thumbnails always enabled - core functionality
        
        photo = await self._get_photo(file_hash)
        if not photo:
            self._log_error(file_hash, None, "Photo not found in database")
            return False

        filepath = settings.photos_dir / photo.file_path

        if thumb_exists(file_hash):
            logger.debug(f"[thumbnails] Skip: {photo.file_path} (already exists)")
            await self.pipeline.route_to_next(file_hash, QueueType.THUMBNAILS)
            return True

        self.queue.current_file_hash = file_hash
        self.queue.current_file_path = str(filepath)
        logger.info(f"[thumbnails] Processing: {photo.file_path}")

        try:
            success = await generate_thumbnails(file_hash)
            if success:
                logger.info(f"[thumbnails] Done: {photo.file_path}")
            else:
                self._log_error(file_hash, str(filepath), "Thumbnail generation failed")
                logger.warning(f"[thumbnails] Failed: {photo.file_path}")
        except Exception as e:
            logger.warning(f"[thumbnails] Failed: {photo.file_path} - {type(e).__name__}")
            self._log_error(file_hash, str(filepath), str(e)[:100])

        self.queue.current_file_hash = None
        self.queue.current_file_path = None
        await self.pipeline.route_to_next(file_hash, QueueType.THUMBNAILS)
        return True

    async def _process_motion_photos(self, file_hash: str) -> bool:
        """Process motion photo extraction stage."""
        # Motion photos always enabled

        photo = await self._get_photo(file_hash)
        if not photo:
            return False

        filepath = settings.photos_dir / photo.file_path
        logger.info(f"[motion] Processing: {photo.file_path}")
        self.queue.current_file_hash = file_hash
        self.queue.current_file_path = str(filepath)

        try:
            result = await extract_motion_video(file_hash)
            if result:
                logger.info(f"[motion] Done: {photo.file_path} (motion video extracted)")
            else:
                logger.debug(f"[motion] Done: {photo.file_path} (not a motion photo)")
        except Exception as e:
            logger.warning(f"[motion] Failed: {photo.file_path} - {e}")

        self.queue.current_file_hash = None
        self.queue.current_file_path = None
        await self.pipeline.route_to_next(file_hash, QueueType.MOTION_PHOTOS)
        return True

    async def _process_hashing(self, file_hash: str) -> bool:
        """Process perceptual hashing stage."""
        # Hashing always enabled - core functionality
        
        photo = await self._get_photo(file_hash)
        if not photo:
            return False

        filepath = settings.photos_dir / photo.file_path

        if await self._has_photo_hash(file_hash):
            logger.debug(f"[hashing] Skip: {photo.file_path} (already hashed)")
            await self.pipeline.route_to_next(file_hash, QueueType.HASHING)
            return True

        self.queue.current_file_hash = file_hash
        self.queue.current_file_path = str(filepath)
        logger.info(f"[hashing] Processing: {photo.file_path}")

        try:
            success = await compute_hashes(file_hash)
            if success:
                logger.info(f"[hashing] Done: {photo.file_path}")
            else:
                self._log_error(file_hash, str(filepath), "Hashing failed")
                logger.warning(f"[hashing] Failed: {photo.file_path}")
        except Exception as e:
            logger.warning(f"[hashing] Failed: {photo.file_path} - {e}")
            self._log_error(file_hash, str(filepath), str(e)[:100])

        self.queue.current_file_hash = None
        self.queue.current_file_path = None
        await self.pipeline.route_to_next(file_hash, QueueType.HASHING)
        return True

    async def _process_faces(self, file_hash: str) -> bool:
        """Process face detection stage."""
        if not settings.ENABLE_FACE_DETECTION:
            await self.pipeline.route_to_next(file_hash, QueueType.FACES)
            return True

        photo = await self._get_photo(file_hash)
        if not photo:
            return False

        filepath = settings.photos_dir / photo.file_path

        if await self._has_faces(file_hash):
            logger.debug(f"[faces] Skip: {photo.file_path} (already processed)")
            await self.pipeline.route_to_next(file_hash, QueueType.FACES)
            return True

        self.queue.current_file_hash = file_hash
        self.queue.current_file_path = str(filepath)
        logger.info(f"[faces] Processing: {photo.file_path}")

        try:
            await detect_faces(file_hash)
            # Check how many faces were found
            async with async_session() as session:
                result = await session.execute(
                    select(func.count(Face.face_id)).where(Face.file_hash == file_hash)
                )
                count = result.scalar() or 0
                if count > 0:
                    logger.info(f"[faces] Done: {photo.file_path} ({count} face{'s' if count != 1 else ''} found)")
                else:
                    logger.info(f"[faces] Done: {photo.file_path} (no faces)")
        except Exception as e:
            logger.warning(f"[faces] Failed: {photo.file_path} - {e}")
            self._log_error(file_hash, str(filepath), str(e)[:100])

        self.queue.current_file_hash = None
        self.queue.current_file_path = None
        await self.pipeline.route_to_next(file_hash, QueueType.FACES)
        return True

    async def _process_captioning(self, file_hash: str) -> bool:
        """Process AI captioning stage."""
        if not settings.ENABLE_CAPTIONING:
            await self.pipeline.route_to_next(file_hash, QueueType.CAPTIONING)
            return True

        photo = await self._get_photo(file_hash)
        if not photo:
            return False

        filepath = settings.photos_dir / photo.file_path

        if await self._has_caption(file_hash):
            logger.debug(f"[captioning] Skip: {photo.file_path} (already captioned)")
            await self.pipeline.route_to_next(file_hash, QueueType.CAPTIONING)
            return True

        self.queue.current_file_hash = file_hash
        self.queue.current_file_path = str(filepath)
        logger.info(f"[captioning] Processing: {photo.file_path}")

        try:
            await caption_photo(file_hash)
            # Get the generated caption
            async with async_session() as session:
                result = await session.execute(
                    select(Caption).where(Caption.file_hash == file_hash)
                )
                caption = result.scalar_one_or_none()
                if caption and caption.caption:
                    preview = caption.caption[:80] + "..." if len(caption.caption) > 80 else caption.caption
                    logger.info(f"[captioning] Done: {photo.file_path} -> \"{preview}\"")
                else:
                    logger.info(f"[captioning] Done: {photo.file_path} (no caption generated)")
        except Exception as e:
            logger.warning(f"[captioning] Failed: {photo.file_path} - {e}")
            self._log_error(file_hash, str(filepath), str(e)[:100])

        self.queue.current_file_hash = None
        self.queue.current_file_path = None
        await self.pipeline.route_to_next(file_hash, QueueType.CAPTIONING)
        return True

    async def _process_events(self, file_hash: str) -> bool:
        """Process event detection stage - just queue for batch processing."""
        return True

    async def process_item(self, file_hash: str) -> bool:
        """Process a single item from the queue."""
        handlers = {
            QueueType.EXIF: self._process_exif,
            QueueType.GEOCODING: self._process_geocoding,
            QueueType.THUMBNAILS: self._process_thumbnails,
            QueueType.MOTION_PHOTOS: self._process_motion_photos,
            QueueType.HASHING: self._process_hashing,
            QueueType.FACES: self._process_faces,
            QueueType.CAPTIONING: self._process_captioning,
            QueueType.EVENTS: self._process_events,
        }

        handler = handlers.get(self.queue_type)
        if handler:
            result = await handler(file_hash)
            self._log_progress()
            return result
        return False

    def _log_progress(self):
        """Log progress every 100 items."""
        queue_name = self.queue_type.value
        if queue_name not in Worker._progress_counts:
            Worker._progress_counts[queue_name] = 0
            Worker._progress_logs[queue_name] = 0
        
        Worker._progress_counts[queue_name] += 1
        count = Worker._progress_counts[queue_name]
        last_milestone = Worker._progress_logs[queue_name]
        
        # Log every 100 items
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
                except:
                    break

            if drained == 0:
                continue

            logger.debug(f"Event worker: drained {drained} items")

            # Wait for upstream to settle
            await asyncio.sleep(5)

            # Face clustering - runs on every drain (already fixed to only process unassigned faces)
            if settings.ENABLE_FACE_DETECTION:
                logger.debug("Running batch face clustering...")
                try:
                    await cluster_faces()
                except Exception as e:
                    logger.warning(f"Face clustering failed: {type(e).__name__}")

            # Event detection - debounced to run at most once per minute during active processing
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


async def start_pipeline_workers(pipeline: Pipeline) -> list[asyncio.Task]:
    """Start workers for all queues."""
    workers = []

    for queue_type in QueueType:
        if queue_type == QueueType.EVENTS:
            continue

        worker = Worker(pipeline, queue_type, worker_id=len(workers))
        task = asyncio.create_task(worker.run())
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