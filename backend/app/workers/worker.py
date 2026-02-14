"""Pipeline workers for parallel photo processing.

Simplified architecture:
- Workers check if processing is needed by looking at actual data existence
- No in-memory counters or _processed sets
- Config flags control whether each stage runs
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import select, func

from backend.app.config import settings
from backend.app.database import async_session, get_session
from backend.app.models import Photo, PhotoHash, Face, Caption
from backend.app.services.exif import extract_exif
from backend.app.services.thumbnail import generate_thumbnails
from backend.app.services.hasher import compute_hashes
from backend.app.services.geocoder import geocode_photo
from backend.app.services.face_detector import detect_faces, cluster_faces
from backend.app.services.captioner import caption_photo
from backend.app.services.event_detector import detect_events
from backend.app.services.motion_photo import extract_motion_video
from backend.app.workers.queues import Pipeline, QueueType

logger = logging.getLogger(__name__)

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

    def _thumb_exists(self, file_hash: str) -> bool:
        """Check if thumbnail file exists on disk."""
        prefix = file_hash[:2]
        thumb_path = settings.thumbnails_dir / prefix / f"{file_hash}_200.webp"
        return thumb_path.exists()

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

        if self._exif_exists(photo):
            logger.debug(f"EXIF already exists for {file_hash}")
            await self.pipeline.route_to_next(file_hash, QueueType.EXIF)
            return True

        filepath = settings.photos_dir / photo.file_path
        self.queue.current_file_hash = file_hash
        self.queue.current_file_path = str(filepath)

        try:
            success = await extract_exif(file_hash)
            if success:
                logger.debug(f"EXIF extracted for {file_hash}")
            else:
                self._log_error(file_hash, str(filepath), "EXIF extraction failed")
        except Exception as e:
            logger.exception(f"EXIF extraction failed for {file_hash}")
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

        if photo.location_city is not None:
            await self.pipeline.route_to_next(file_hash, QueueType.GEOCODING)
            return True

        try:
            await geocode_photo(file_hash)
        except Exception as e:
            logger.warning(f"Geocoding failed for {file_hash}: {e}")

        await self.pipeline.route_to_next(file_hash, QueueType.GEOCODING)
        return True

    async def _process_thumbnails(self, file_hash: str) -> bool:
        """Process thumbnail generation stage."""
        # Thumbnails always enabled - core functionality
        
        if self._thumb_exists(file_hash):
            logger.debug(f"Thumbnails already exist for {file_hash}")
            await self.pipeline.route_to_next(file_hash, QueueType.THUMBNAILS)
            return True

        photo = await self._get_photo(file_hash)
        if not photo:
            self._log_error(file_hash, None, "Photo not found in database")
            return False

        filepath = settings.photos_dir / photo.file_path
        self.queue.current_file_hash = file_hash
        self.queue.current_file_path = str(filepath)

        try:
            success = await generate_thumbnails(file_hash)
            if not success:
                self._log_error(file_hash, str(filepath), "Thumbnail generation failed")
        except Exception as e:
            logger.exception(f"Thumbnail generation failed for {file_hash}")
            self._log_error(file_hash, str(filepath), str(e)[:100])

        self.queue.current_file_hash = None
        self.queue.current_file_path = None
        await self.pipeline.route_to_next(file_hash, QueueType.THUMBNAILS)
        return True

    async def _process_motion_photos(self, file_hash: str) -> bool:
        """Process motion photo extraction stage."""
        # Motion photos always enabled
        
        try:
            await extract_motion_video(file_hash)
        except Exception as e:
            logger.warning(f"Motion photo extraction failed for {file_hash}: {e}")

        await self.pipeline.route_to_next(file_hash, QueueType.MOTION_PHOTOS)
        return True

    async def _process_hashing(self, file_hash: str) -> bool:
        """Process perceptual hashing stage."""
        # Hashing always enabled - core functionality
        
        if await self._has_photo_hash(file_hash):
            logger.debug(f"Hash already exists for {file_hash}")
            await self.pipeline.route_to_next(file_hash, QueueType.HASHING)
            return True

        photo = await self._get_photo(file_hash)
        filepath = settings.photos_dir / photo.file_path if photo else None
        self.queue.current_file_hash = file_hash
        self.queue.current_file_path = str(filepath) if filepath else None

        try:
            success = await compute_hashes(file_hash)
            if not success:
                self._log_error(file_hash, str(filepath) if filepath else None, "Hashing failed")
        except Exception as e:
            logger.warning(f"Hashing failed for {file_hash}: {e}")
            self._log_error(file_hash, str(filepath) if filepath else None, str(e)[:100])

        self.queue.current_file_hash = None
        self.queue.current_file_path = None
        await self.pipeline.route_to_next(file_hash, QueueType.HASHING)
        return True

    async def _process_faces(self, file_hash: str) -> bool:
        """Process face detection stage."""
        if not settings.ENABLE_FACE_DETECTION:
            await self.pipeline.route_to_next(file_hash, QueueType.FACES)
            return True

        if await self._has_faces(file_hash):
            logger.debug(f"Faces already detected for {file_hash}")
            await self.pipeline.route_to_next(file_hash, QueueType.FACES)
            return True

        photo = await self._get_photo(file_hash)
        filepath = settings.photos_dir / photo.file_path if photo else None
        self.queue.current_file_hash = file_hash
        self.queue.current_file_path = str(filepath) if filepath else None

        try:
            await detect_faces(file_hash)
        except Exception as e:
            logger.warning(f"Face detection failed for {file_hash}: {e}")
            self._log_error(file_hash, str(filepath) if filepath else None, str(e)[:100])

        self.queue.current_file_hash = None
        self.queue.current_file_path = None
        await self.pipeline.route_to_next(file_hash, QueueType.FACES)
        return True

    async def _process_captioning(self, file_hash: str) -> bool:
        """Process AI captioning stage."""
        if not settings.ENABLE_CAPTIONING:
            await self.pipeline.route_to_next(file_hash, QueueType.CAPTIONING)
            return True

        if await self._has_caption(file_hash):
            logger.debug(f"Caption already exists for {file_hash}")
            await self.pipeline.route_to_next(file_hash, QueueType.CAPTIONING)
            return True

        photo = await self._get_photo(file_hash)
        filepath = settings.photos_dir / photo.file_path if photo else None
        self.queue.current_file_hash = file_hash
        self.queue.current_file_path = str(filepath) if filepath else None

        try:
            await caption_photo(file_hash)
        except Exception as e:
            logger.warning(f"Captioning failed for {file_hash}: {e}")
            self._log_error(file_hash, str(filepath) if filepath else None, str(e)[:100])

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
            return await handler(file_hash)
        return False

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
            except Exception:
                logger.exception(f"Unhandled error in worker {self.worker_id} ({self.queue_type.value})")
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

    async def run(self):
        """Run the event detection worker."""
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

            logger.info(f"Event worker: drained {drained} items")

            # Wait for upstream to settle
            await asyncio.sleep(5)

            # Run batch operations
            if settings.ENABLE_FACE_DETECTION:
                logger.info("Running batch face clustering...")
                try:
                    await cluster_faces()
                except Exception:
                    logger.exception("Face clustering failed")

            logger.info("Running batch event detection...")
            try:
                await detect_events()
            except Exception:
                logger.exception("Event detection failed")

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