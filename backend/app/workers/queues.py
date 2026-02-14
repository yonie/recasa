"""Pipeline queue system for parallel photo processing.

Simplified architecture:
- asyncio.Queue for flow control and worker parallelism
- NO in-memory counters (query DB for progress)
- NO _processed sets (check DB/disk for existence)
- DB and filesystem are the source of truth

Workers check if processing is needed before each stage (idempotent).
"""

import asyncio
import logging
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class QueueType(Enum):
    EXIF = "exif"
    GEOCODING = "geocoding"
    THUMBNAILS = "thumbnails"
    MOTION_PHOTOS = "motion_photos"
    HASHING = "hashing"
    FACES = "faces"
    CAPTIONING = "captioning"
    EVENTS = "events"


class ProcessingQueue:
    """A simple queue for processing photos through a specific stage.

    No counters, no processed tracking. Just an asyncio.Queue for flow control.
    """

    def __init__(self, queue_type: QueueType, max_size: int = 50000):
        self.queue_type = queue_type
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=max_size)
        self.current_file_hash: str | None = None
        self.current_file_path: str | None = None

    async def put(self, file_hash: str) -> bool:
        """Add a file hash to the queue. Returns True if successful."""
        try:
            self.queue.put_nowait(file_hash)
            return True
        except asyncio.QueueFull:
            logger.warning(f"Queue {self.queue_type.value} is full, dropping {file_hash}")
            return False

    async def get(self) -> str:
        """Get the next file hash from the queue."""
        return await self.queue.get()

    def qsize(self) -> int:
        """Get the current queue size."""
        return self.queue.qsize()

    def empty(self) -> bool:
        """Check if queue is empty."""
        return self.queue.empty()


class Pipeline:
    """Orchestrates the photo processing pipeline with parallel queues.

    Each queue is just an asyncio.Queue for flow control.
    Progress is tracked by querying the database, not in-memory counters.
    """

    def __init__(self):
        self.queues: dict[QueueType, ProcessingQueue] = {}
        self.workers: list[asyncio.Task] = []
        self.is_running = False
        self._stop_requested = False
        self.error_log: list[dict] = []

        # Create queues
        for qtype in QueueType:
            self.queues[qtype] = ProcessingQueue(qtype)

        # Define pipeline flow - sequential per file
        self._flow: dict[QueueType, list[QueueType]] = {
            QueueType.EXIF: [QueueType.GEOCODING],
            QueueType.GEOCODING: [QueueType.THUMBNAILS],
            QueueType.THUMBNAILS: [QueueType.MOTION_PHOTOS],
            QueueType.MOTION_PHOTOS: [QueueType.HASHING],
            QueueType.HASHING: [QueueType.FACES],
            QueueType.FACES: [QueueType.CAPTIONING],
            QueueType.CAPTIONING: [QueueType.EVENTS],
            QueueType.EVENTS: [],
        }

    def get_next_queues(self, queue_type: QueueType) -> list[QueueType]:
        """Get the next queues in the pipeline flow."""
        return self._flow.get(queue_type, [])

    async def add_file(self, file_hash: str) -> bool:
        """Add a newly discovered file to the pipeline (starts at EXIF)."""
        return await self.queues[QueueType.EXIF].put(file_hash)

    async def add_file_at(self, file_hash: str, entry_queue: QueueType) -> bool:
        """Add a file to the pipeline at a specific queue."""
        return await self.queues[entry_queue].put(file_hash)

    async def route_to_next(self, file_hash: str, from_queue: QueueType):
        """Route a file to the next queue(s) in the pipeline."""
        next_queues = self.get_next_queues(from_queue)
        for next_queue_type in next_queues:
            await self.queues[next_queue_type].put(file_hash)

    def add_error(self, queue: str, file_hash: str, file_path: str | None, error: str):
        """Add an error to the error log."""
        import datetime
        self.error_log.append({
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "queue": queue,
            "file_hash": file_hash,
            "file_path": file_path,
            "error": error[:200],
        })
        if len(self.error_log) > 100:
            self.error_log = self.error_log[-100:]

    def get_queue_sizes(self) -> dict[str, int]:
        """Get current queue sizes."""
        return {
            qtype.value: queue.qsize()
            for qtype, queue in self.queues.items()
        }


# Global pipeline instance
pipeline = Pipeline()