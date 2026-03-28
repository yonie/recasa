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
from watchdog.events import FileSystemEventHandler

from backend.app.config import settings
from backend.app.services.scanner import scan_directory, index_single_file, is_supported_photo, thumb_exists
from backend.app.workers.queues import pipeline, QueueType
from backend.app.database import async_session
from backend.app.models import Photo, PhotoHash, Face, Caption
from sqlalchemy import select, func

logger = logging.getLogger(__name__)

STAGE_TO_QUEUE: dict[str, QueueType] = {
    "exif": QueueType.EXIF,
    "geocoding": QueueType.GEOCODING,
    "thumbnails": QueueType.THUMBNAILS,
    "hashing": QueueType.HASHING,
    "faces": QueueType.FACES,
    "captioning": QueueType.CAPTIONING,
}


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
        queue_type = STAGE_TO_QUEUE.get(entry_stage)
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
    Each photo is queued at its earliest incomplete stage only -- the pipeline
    routing will carry it through subsequent stages automatically.
    Returns the number of photos queued.
    """
    # Collect sets of file_hashes needing each stage (ordered earliest to latest)
    # Stage order matches the pipeline flow: EXIF -> GEOCODING -> THUMBNAILS -> HASHING -> FACES -> CAPTIONING
    needs: dict[QueueType, set[str]] = {}

    # EXIF: photos missing camera_make AND date_taken (always enabled)
    async with async_session() as session:
        result = await session.execute(
            select(Photo.file_hash).where(
                Photo.camera_make.is_(None),
                Photo.date_taken.is_(None)
            )
        )
        needs[QueueType.EXIF] = {row[0] for row in result.fetchall()}
        logger.info(f"Found {len(needs[QueueType.EXIF])} photos needing EXIF extraction")

    # Geocoding: photos with GPS but no city
    if settings.ENABLE_GEOCODING:
        async with async_session() as session:
            result = await session.execute(
                select(Photo.file_hash).where(
                    Photo.location_city.is_(None),
                    Photo.gps_latitude.is_not(None)
                )
            )
            needs[QueueType.GEOCODING] = {row[0] for row in result.fetchall()}
            logger.info(f"Found {len(needs[QueueType.GEOCODING])} photos needing geocoding")

    # Thumbnails: photos missing thumb file (always enabled)
    async with async_session() as session:
        result = await session.execute(select(Photo.file_hash))
        all_hashes = [row[0] for row in result.fetchall()]
        needs[QueueType.THUMBNAILS] = {fh for fh in all_hashes if not thumb_exists(fh)}
        logger.info(f"Found {len(needs[QueueType.THUMBNAILS])} photos needing thumbnails")

    # Hashing: photos missing perceptual hash (always enabled)
    async with async_session() as session:
        result = await session.execute(
            select(Photo.file_hash).where(
                ~Photo.file_hash.in_(select(PhotoHash.file_hash))
            )
        )
        needs[QueueType.HASHING] = {row[0] for row in result.fetchall()}
        logger.info(f"Found {len(needs[QueueType.HASHING])} photos needing hashing")

    # Faces: photos missing faces
    if settings.ENABLE_FACE_DETECTION:
        async with async_session() as session:
            result = await session.execute(
                select(Photo.file_hash).where(
                    ~Photo.file_hash.in_(select(Face.file_hash))
                )
            )
            needs[QueueType.FACES] = {row[0] for row in result.fetchall()}
            logger.info(f"Found {len(needs[QueueType.FACES])} photos needing face detection")

    # Captioning: photos missing caption
    if settings.ENABLE_CAPTIONING:
        async with async_session() as session:
            result = await session.execute(
                select(Photo.file_hash).where(
                    ~Photo.file_hash.in_(select(Caption.file_hash))
                )
            )
            needs[QueueType.CAPTIONING] = {row[0] for row in result.fetchall()}
            logger.info(f"Found {len(needs[QueueType.CAPTIONING])} photos needing captioning")

    # Deduplicate: queue each photo at its earliest incomplete stage only.
    # Pipeline routing carries it through subsequent stages.
    stage_order = [QueueType.EXIF, QueueType.GEOCODING, QueueType.THUMBNAILS,
                   QueueType.HASHING, QueueType.FACES, QueueType.CAPTIONING]
    already_queued: set[str] = set()
    queued_count = 0

    for stage in stage_order:
        if stage not in needs:
            continue
        to_queue = needs[stage] - already_queued
        for file_hash in to_queue:
            await pipeline.add_file_at(file_hash, stage)
            queued_count += 1
        already_queued |= needs[stage]
        if to_queue:
            logger.info(f"Queued {len(to_queue)} photos at {stage.value} (earliest incomplete stage)")

    if queued_count > 0:
        logger.info(f"Total: {queued_count} photos queued for processing")
    else:
        logger.info("All photos are fully processed")

    return queued_count


class FileEventHandler(FileSystemEventHandler):
    """Handle file system events for new/modified photos."""

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop

    def on_created(self, event):
        if event.is_directory:
            return
        filepath = Path(event.src_path)
        if is_supported_photo(filepath):
            asyncio.run_coroutine_threadsafe(self._queue_file(filepath), self.loop)

    def on_modified(self, event):
        if event.is_directory:
            return
        filepath = Path(event.src_path)
        if is_supported_photo(filepath):
            asyncio.run_coroutine_threadsafe(self._queue_file(filepath), self.loop)

    async def _queue_file(self, filepath: Path):
        result = await index_single_file(filepath)
        if result:
            file_hash, entry_queue = result
            queue_type = STAGE_TO_QUEUE.get(entry_queue)
            if queue_type:
                await pipeline.add_file_at(file_hash, queue_type)
                logger.info(f"Indexed new file: {filepath} ({file_hash})")


async def start_file_watcher():
    """Start watching the photos directory for new files."""
    handler = FileEventHandler(asyncio.get_running_loop())
    observer = Observer()
    observer.schedule(handler, str(settings.photos_dir), recursive=True)
    observer.start()
    logger.info(f"File watcher started for {settings.photos_dir}")
    return observer