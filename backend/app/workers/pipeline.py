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

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent

from backend.app.config import settings
from backend.app.services.scanner import scan_directory, index_single_file, is_supported_photo
from backend.app.workers.queues import pipeline, QueueType
from backend.app.database import async_session
from backend.app.models import Photo, PhotoHash, Face, Caption
from sqlalchemy import select, func

logger = logging.getLogger(__name__)


async def run_initial_scan() -> dict:
    """Run the initial directory scan and queue photos for processing.

    Each photo is queued for the first stage that needs processing based on:
    - Config flags (ENABLE_*)
    - Actual data/file existence
    """
    from backend.app.services.scanner import thumb_exists

    async def progress_callback(processed: int, total: int, current_file: str):
        logger.info(f"Scanning: {processed}/{total}")

    async def on_file_discovered(file_hash: str, entry_stage: str):
        """Queue a photo for processing at the appropriate stage."""
        stage_to_queue = {
            "exif": QueueType.EXIF,
            "geocoding": QueueType.GEOCODING,
            "thumbnails": QueueType.THUMBNAILS,
            "hashing": QueueType.HASHING,
            "faces": QueueType.FACES,
            "captioning": QueueType.CAPTIONING,
        }
        queue_type = stage_to_queue.get(entry_stage)
        if queue_type:
            await pipeline.add_file_at(file_hash, queue_type)
            logger.debug(f"Queued {file_hash} for {entry_stage}")

    stats = await scan_directory(
        progress_callback=progress_callback,
        cancel_check=lambda: pipeline._stop_requested,
        on_file_discovered=on_file_discovered,
    )
    return stats


async def resume_incomplete_processing() -> int:
    """Queue photos that have incomplete processing based on config and actual data.

    Called on startup to resume processing after a crash or restart.
    Returns the number of photos queued.
    """
    queued_count = 0

    # EXIF: photos missing camera_make AND date_taken (always enabled)
    async with async_session() as session:
        result = await session.execute(
            select(Photo.file_hash).where(
                Photo.camera_make.is_(None),
                Photo.date_taken.is_(None)
            )
        )
        photos = result.fetchall()
        for (file_hash,) in photos:
            await pipeline.add_file_at(file_hash, QueueType.EXIF)
            queued_count += 1
        logger.info(f"Queued {len(photos)} photos for EXIF extraction")

    # Geocoding: photos with GPS but no city
    if settings.ENABLE_GEOCODING:
        async with async_session() as session:
            result = await session.execute(
                select(Photo.file_hash).where(
                    Photo.location_city.is_(None),
                    Photo.gps_latitude.is_not(None)
                )
            )
            photos = result.fetchall()
            for (file_hash,) in photos:
                await pipeline.add_file_at(file_hash, QueueType.GEOCODING)
                queued_count += 1
            logger.info(f"Queued {len(photos)} photos for geocoding")

    # Thumbnails: photos missing thumb file (always enabled)
    async with async_session() as session:
        result = await session.execute(select(Photo.file_hash))
        photos = result.fetchall()
        missing_thumbs = 0
        for (file_hash,) in photos:
            if not (settings.thumbnails_dir / f"{file_hash}_200.jpg").exists():
                await pipeline.add_file_at(file_hash, QueueType.THUMBNAILS)
                missing_thumbs += 1
                queued_count += 1
        logger.info(f"Queued {missing_thumbs} photos for thumbnail generation")

    # Hashing: photos missing perceptual hash (always enabled)
    async with async_session() as session:
        result = await session.execute(
            select(Photo.file_hash).where(
                ~Photo.file_hash.in_(select(PhotoHash.file_hash))
            )
        )
        photos = result.fetchall()
        for (file_hash,) in photos:
            await pipeline.add_file_at(file_hash, QueueType.HASHING)
            queued_count += 1
        logger.info(f"Queued {len(photos)} photos for perceptual hashing")

    # Faces: photos missing faces
    if settings.ENABLE_FACE_DETECTION:
        async with async_session() as session:
            result = await session.execute(
                select(Photo.file_hash).where(
                    ~Photo.file_hash.in_(select(Face.file_hash))
                )
            )
            photos = result.fetchall()
            for (file_hash,) in photos:
                await pipeline.add_file_at(file_hash, QueueType.FACES)
                queued_count += 1
            logger.info(f"Queued {len(photos)} photos for face detection")

    # Captioning: photos missing caption
    if settings.ENABLE_CAPTIONING:
        async with async_session() as session:
            result = await session.execute(
                select(Photo.file_hash).where(
                    ~Photo.file_hash.in_(select(Caption.file_hash))
                )
            )
            photos = result.fetchall()
            for (file_hash,) in photos:
                await pipeline.add_file_at(file_hash, QueueType.CAPTIONING)
                queued_count += 1
            logger.info(f"Queued {len(photos)} photos for captioning")

    if queued_count > 0:
        logger.info(f"Total: {queued_count} photos queued for processing")
    else:
        logger.info("All photos are fully processed")

    return queued_count


class FileEventHandler(FileSystemEventHandler):
    """Handle file system events for new/modified photos."""

    def __init__(self, queue: asyncio.Queue):
        self.queue = queue

    def on_created(self, event):
        if event.is_directory:
            return
        filepath = Path(event.src_path)
        if is_supported_photo(filepath):
            asyncio.create_task(self._queue_file(filepath))

    def on_modified(self, event):
        if event.is_directory:
            return
        filepath = Path(event.src_path)
        if is_supported_photo(filepath):
            asyncio.create_task(self._queue_file(filepath))

    async def _queue_file(self, filepath: Path):
        result = await index_single_file(filepath)
        if result:
            file_hash, entry_queue = result
            stage_to_queue = {
                "exif": QueueType.EXIF,
                "geocoding": QueueType.GEOCODING,
                "thumbnails": QueueType.THUMBNAILS,
                "hashing": QueueType.HASHING,
                "faces": QueueType.FACES,
                "captioning": QueueType.CAPTIONING,
            }
            queue_type = stage_to_queue.get(entry_queue)
            if queue_type:
                await pipeline.add_file_at(file_hash, queue_type)
                logger.info(f"Indexed new file: {filepath} ({file_hash})")


async def start_file_watcher():
    """Start watching the photos directory for new files."""
    handler = FileEventHandler(asyncio.Queue())
    observer = Observer()
    observer.schedule(handler, str(settings.photos_dir), recursive=True)
    observer.start()
    logger.info(f"File watcher started for {settings.photos_dir}")
    return observer