"""Pipeline workers for parallel photo processing."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from backend.app.config import settings
from backend.app.database import async_session
from backend.app.models import Photo
from backend.app.services.exif import extract_exif
from backend.app.services.thumbnail import generate_thumbnails
from backend.app.services.hasher import compute_hashes
from backend.app.services.geocoder import geocode_photo
from backend.app.services.clip_tagger import tag_photo
from backend.app.services.face_detector import detect_faces, cluster_faces
from backend.app.services.captioner import caption_photo
from backend.app.services.event_detector import detect_events
from backend.app.services.motion_photo import extract_motion_video
from backend.app.workers.queues import Pipeline, QueueType

logger = logging.getLogger(__name__)


class Worker:
    """Worker that processes files from a specific queue."""

    def __init__(self, pipeline: Pipeline, queue_type: QueueType, worker_id: int = 0):
        self.pipeline = pipeline
        self.queue_type = queue_type
        self.worker_id = worker_id
        self.queue = pipeline.queues[queue_type]
        self._running = False

    async def _get_file_path(self, file_hash: str) -> Path | None:
        """Get the file path for a file hash."""
        async with async_session() as session:
            photo = await session.get(Photo, file_hash)
            if photo:
                return settings.photos_dir / photo.file_path
        return None

    async def _process_discovery(self, file_hash: str) -> bool:
        """Process discovery stage - file already discovered, just route to next."""
        await self.queue.mark_processing(file_hash, None)
        await self.pipeline.route_to_next(file_hash, QueueType.DISCOVERY)
        await self.queue.mark_completed(file_hash)
        return True

    async def _process_exif(self, file_hash: str) -> bool:
        """Process EXIF extraction stage."""
        filepath = await self._get_file_path(file_hash)
        if not filepath:
            await self.queue.mark_failed(file_hash)
            return False

        await self.queue.mark_processing(file_hash, str(filepath))

        # Check if already extracted
        async with async_session() as session:
            photo = await session.get(Photo, file_hash)
            if photo and photo.exif_extracted:
                await self.queue.mark_completed(file_hash)
                await self.pipeline.route_to_next(file_hash, QueueType.EXIF)
                return True

        if await extract_exif(file_hash):
            await self.queue.mark_completed(file_hash)
            await self.pipeline.route_to_next(file_hash, QueueType.EXIF)
            return True
        else:
            await self.queue.mark_failed(file_hash)
            return False

    async def _process_geocoding(self, file_hash: str) -> bool:
        """Process geocoding stage."""
        await self.queue.mark_processing(file_hash, None)

        # Check if already geocoded
        async with async_session() as session:
            photo = await session.get(Photo, file_hash)
            if photo and photo.location_country:
                await self.queue.mark_completed(file_hash)
                await self.pipeline.route_to_next(file_hash, QueueType.GEOCODING)
                return True

        if await geocode_photo(file_hash):
            await self.queue.mark_completed(file_hash)
            await self.pipeline.route_to_next(file_hash, QueueType.GEOCODING)
            return True
        else:
            # Geocoding failure is not critical - still proceed
            await self.queue.mark_completed(file_hash)
            await self.pipeline.route_to_next(file_hash, QueueType.GEOCODING)
            return True

    async def _process_thumbnails(self, file_hash: str) -> bool:
        """Process thumbnail generation stage."""
        filepath = await self._get_file_path(file_hash)
        if not filepath:
            await self.queue.mark_failed(file_hash)
            return False

        await self.queue.mark_processing(file_hash, str(filepath))

        # Check if already generated
        async with async_session() as session:
            photo = await session.get(Photo, file_hash)
            if photo and photo.thumbnail_generated:
                await self.queue.mark_completed(file_hash)
                await self.pipeline.route_to_next(file_hash, QueueType.THUMBNAILS)
                return True

        if await generate_thumbnails(file_hash):
            await self.queue.mark_completed(file_hash)
            await self.pipeline.route_to_next(file_hash, QueueType.THUMBNAILS)
            return True
        else:
            await self.queue.mark_failed(file_hash)
            return False

    async def _process_motion_photos(self, file_hash: str) -> bool:
        """Process motion photo extraction stage."""
        filepath = await self._get_file_path(file_hash)
        if not filepath:
            await self.queue.mark_failed(file_hash)
            return False

        await self.queue.mark_processing(file_hash, str(filepath))

        if await extract_motion_video(file_hash):
            await self.queue.mark_completed(file_hash)
            await self.pipeline.route_to_next(file_hash, QueueType.MOTION_PHOTOS)
            return True
        else:
            await self.queue.mark_completed(file_hash)  # Not critical
            await self.pipeline.route_to_next(file_hash, QueueType.MOTION_PHOTOS)
            return True

    async def _process_hashing(self, file_hash: str) -> bool:
        """Process perceptual hashing stage."""
        await self.queue.mark_processing(file_hash, None)

        # Check if already hashed
        async with async_session() as session:
            photo = await session.get(Photo, file_hash)
            if photo and photo.perceptual_hashed:
                await self.queue.mark_completed(file_hash)
                await self.pipeline.route_to_next(file_hash, QueueType.HASHING)
                return True

        if await compute_hashes(file_hash):
            await self.queue.mark_completed(file_hash)
            await self.pipeline.route_to_next(file_hash, QueueType.HASHING)
            return True
        else:
            await self.queue.mark_failed(file_hash)
            return False

    async def _process_clip(self, file_hash: str) -> bool:
        """Process CLIP tagging stage."""
        await self.queue.mark_processing(file_hash, None)

        # Check if already tagged
        async with async_session() as session:
            photo = await session.get(Photo, file_hash)
            if photo and photo.clip_tagged:
                await self.queue.mark_completed(file_hash)
                await self.pipeline.route_to_next(file_hash, QueueType.CLIP)
                return True

        try:
            result = await tag_photo(file_hash)
            if not result:
                logger.warning("CLIP tagging returned False for %s (model may not be available)", file_hash)
            await self.queue.mark_completed(file_hash)
            await self.pipeline.route_to_next(file_hash, QueueType.CLIP)
            return True
        except Exception:
            logger.exception("CLIP tagging failed for %s", file_hash)
            # CLIP is optional -- don't block the pipeline
            await self.queue.mark_completed(file_hash)
            await self.pipeline.route_to_next(file_hash, QueueType.CLIP)
            return True

    async def _process_faces(self, file_hash: str) -> bool:
        """Process face detection stage."""
        await self.queue.mark_processing(file_hash, None)

        # Check if already processed
        async with async_session() as session:
            photo = await session.get(Photo, file_hash)
            if photo and photo.faces_detected:
                await self.queue.mark_completed(file_hash)
                await self.pipeline.route_to_next(file_hash, QueueType.FACES)
                return True

        try:
            result = await detect_faces(file_hash)
            if not result:
                logger.warning("Face detection returned False for %s (model may not be available)", file_hash)
            await self.queue.mark_completed(file_hash)
            await self.pipeline.route_to_next(file_hash, QueueType.FACES)
            return True
        except Exception:
            logger.exception("Face detection failed for %s", file_hash)
            # Face detection is optional -- don't block the pipeline
            await self.queue.mark_completed(file_hash)
            await self.pipeline.route_to_next(file_hash, QueueType.FACES)
            return True

    async def _process_captioning(self, file_hash: str) -> bool:
        """Process Ollama captioning stage."""
        await self.queue.mark_processing(file_hash, None)

        # Check if already captioned
        async with async_session() as session:
            photo = await session.get(Photo, file_hash)
            if photo and photo.ollama_captioned:
                await self.queue.mark_completed(file_hash)
                await self.pipeline.route_to_next(file_hash, QueueType.CAPTIONING)
                return True

        try:
            result = await caption_photo(file_hash)
            if not result:
                logger.debug("Captioning returned False for %s (Ollama may not be available)", file_hash)
            await self.queue.mark_completed(file_hash)
            await self.pipeline.route_to_next(file_hash, QueueType.CAPTIONING)
            return True
        except Exception:
            logger.exception("Captioning failed for %s", file_hash)
            # Captioning is optional -- don't block the pipeline
            await self.queue.mark_completed(file_hash)
            await self.pipeline.route_to_next(file_hash, QueueType.CAPTIONING)
            return True

    async def _process_events(self, file_hash: str) -> bool:
        """Process event detection stage."""
        await self.queue.mark_processing(file_hash, None)

        # Events are handled in batch by EventDetectionWorker, just mark as complete
        await self.queue.mark_completed(file_hash)
        return True

    async def process_item(self, file_hash: str) -> bool:
        """Process a single item from the queue."""
        handlers = {
            QueueType.DISCOVERY: self._process_discovery,
            QueueType.EXIF: self._process_exif,
            QueueType.GEOCODING: self._process_geocoding,
            QueueType.THUMBNAILS: self._process_thumbnails,
            QueueType.MOTION_PHOTOS: self._process_motion_photos,
            QueueType.HASHING: self._process_hashing,
            QueueType.CLIP: self._process_clip,
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
        logger.info(f"Worker {self.worker_id} started for queue {self.queue_type.value}")

        while self._running:
            try:
                file_hash = await asyncio.wait_for(self.queue.get(), timeout=1.0)
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
    """Special worker that runs face clustering + event detection in batch.

    Waits until items arrive in the EVENTS queue (meaning photos have finished
    the full pipeline), then waits for the pipeline to settle before running
    the batch operations.
    """

    def __init__(self, pipeline: Pipeline):
        self.pipeline = pipeline
        self._running = False
        self._task: asyncio.Task | None = None

    async def _detect_events_batch(self):
        """Run event detection on all completed photos."""
        logger.info("Running batch event detection...")
        try:
            n_events = await detect_events()
            logger.info("Batch event detection completed: %d events", n_events)
        except Exception:
            logger.exception("Event detection failed")

    async def _cluster_faces_batch(self):
        """Run face clustering on all detected faces."""
        logger.info("Running batch face clustering...")
        try:
            new_persons = await cluster_faces()
            logger.info("Face clustering completed: %d new persons", new_persons)
        except Exception:
            logger.exception("Face clustering failed")

    def _upstream_busy(self) -> bool:
        """Check if any upstream pipeline stage still has work."""
        return any(
            self.pipeline.queues[qt].stats.pending > 0
            or self.pipeline.queues[qt].stats.processing > 0
            for qt in [
                QueueType.DISCOVERY, QueueType.EXIF, QueueType.GEOCODING,
                QueueType.THUMBNAILS, QueueType.MOTION_PHOTOS,
                QueueType.HASHING, QueueType.CLIP, QueueType.FACES,
                QueueType.CAPTIONING,
            ]
        )

    async def _drain_queue(self) -> int:
        """Drain all pending items from the events queue."""
        events_queue = self.pipeline.queues[QueueType.EVENTS]
        drained = 0
        while True:
            try:
                file_hash = await asyncio.wait_for(events_queue.get(), timeout=0.5)
                await events_queue.mark_completed(file_hash)
                drained += 1
            except asyncio.TimeoutError:
                break
        return drained

    async def run(self):
        """Run the event detection worker."""
        self._running = True
        logger.info("Event detection worker started")

        while self._running:
            try:
                # Wait for the events queue to have items
                events_queue = self.pipeline.queues[QueueType.EVENTS]
                while events_queue.stats.pending == 0 and self._running:
                    await asyncio.sleep(2)

                if not self._running:
                    break

                # Initial debounce -- let more items accumulate
                await asyncio.sleep(5)

                # Drain what we have so far
                drained = await self._drain_queue()
                if drained == 0:
                    continue

                logger.info("Event worker: drained %d items, checking if upstream is busy...", drained)

                # Wait for all upstream stages to finish before running batch ops.
                # This ensures we cluster/detect with the full set of data.
                wait_count = 0
                max_waits = 60  # Max 5 minutes of waiting (60 * 5s)
                while self._upstream_busy() and self._running and wait_count < max_waits:
                    await asyncio.sleep(5)
                    wait_count += 1
                    # Drain any additional items that arrived while waiting
                    extra = await self._drain_queue()
                    if extra:
                        logger.debug("Event worker: drained %d more items while waiting", extra)

                if not self._running:
                    break

                # Final drain after upstream settled
                await self._drain_queue()

                # Run batch operations
                logger.info("Event worker: upstream settled, running batch face clustering + event detection")
                await self._cluster_faces_batch()
                await self._detect_events_batch()

            except Exception:
                logger.exception("Error in event detection worker")
                await asyncio.sleep(5)

        logger.info("Event detection worker stopped")

    def stop(self):
        """Stop the worker."""
        self._running = False
        if self._task:
            self._task.cancel()


async def start_pipeline_workers(pipeline: Pipeline, workers_per_queue: int = 2) -> list[Worker]:
    """Start workers for all queues."""
    workers = []

    # Start workers for each queue type (except EVENTS - handled by EventDetectionWorker)
    for queue_type in QueueType:
        if queue_type == QueueType.EVENTS:
            continue

        for i in range(workers_per_queue):
            worker = Worker(pipeline, queue_type, worker_id=len(workers))
            task = asyncio.create_task(worker.run())
            workers.append(worker)

    # Start event detection worker
    event_worker = EventDetectionWorker(pipeline)
    event_task = asyncio.create_task(event_worker.run())
    workers.append(event_worker)

    pipeline.is_running = True
    pipeline._start_time = datetime.utcnow()

    logger.info(f"Started {len(workers)} pipeline workers")
    return workers


async def stop_pipeline_workers(workers: list[Worker]):
    """Stop all pipeline workers."""
    for worker in workers:
        worker.stop()

    # Give workers time to finish current task
    await asyncio.sleep(1)

    logger.info("All pipeline workers stopped")
