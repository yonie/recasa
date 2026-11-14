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
from datetime import UTC, datetime
from enum import Enum

logger = logging.getLogger(__name__)

# Most recent errors kept for the pipeline status page.
ERROR_LOG_SIZE = 100


class QueueType(Enum):
    EXIF = "exif"
    GEOCODING = "geocoding"
    THUMBNAILS = "thumbnails"
    MOTION_PHOTOS = "motion_photos"
    HASHING = "hashing"
    FACES = "faces"
    CAPTIONING = "captioning"
    EVENTS = "events"


# The order a photo travels through the stages. Every photo that leaves a stage,
# processed or skipped, moves on to the next one; EVENTS is the batch sink.
PIPELINE_ORDER: tuple[QueueType, ...] = (
    QueueType.EXIF,
    QueueType.GEOCODING,
    QueueType.THUMBNAILS,
    QueueType.MOTION_PHOTOS,
    QueueType.HASHING,
    QueueType.FACES,
    QueueType.CAPTIONING,
    QueueType.EVENTS,
)

_NEXT_STAGE: dict[QueueType, QueueType | None] = {
    stage: PIPELINE_ORDER[i + 1] if i + 1 < len(PIPELINE_ORDER) else None
    for i, stage in enumerate(PIPELINE_ORDER)
}


class ProcessingQueue:
    """A simple queue for processing photos through a specific stage.

    No counters, no processed tracking. Just an asyncio.Queue for flow control,
    plus the item in flight so the status page can show it.
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
            logger.warning("Queue %s is full, dropping %s", self.queue_type.value, file_hash)
            return False

    async def get(self) -> str:
        """Get the next file hash from the queue."""
        return await self.queue.get()

    def qsize(self) -> int:
        return self.queue.qsize()

    def empty(self) -> bool:
        return self.queue.empty()

    def drain(self) -> int:
        """Drop everything waiting in the queue. Returns how many were dropped."""
        dropped = 0
        while True:
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                return dropped
            dropped += 1


class Pipeline:
    """Orchestrates the photo processing pipeline with parallel queues.

    Each queue is just an asyncio.Queue for flow control.
    Progress is tracked by querying the database, not in-memory counters.
    """

    def __init__(self):
        self.queues: dict[QueueType, ProcessingQueue] = {
            qtype: ProcessingQueue(qtype) for qtype in QueueType
        }
        self.is_running = False
        # Shown by /api/pipeline/status: a Stop was the last thing to happen.
        # Cleared when new work begins (a scan, a sweep or Resume).
        self._stop_requested = False
        # Bumped by every Stop. Work begun before a Stop (a running scan, an
        # item a worker holds) sees a newer generation and is abandoned;
        # work begun after it runs normally, without a restart.
        self.generation = 0
        self.error_log: list[dict] = []

    def get_next_queues(self, queue_type: QueueType) -> list[QueueType]:
        """The queue(s) a file moves to after leaving `queue_type`."""
        next_stage = _NEXT_STAGE.get(queue_type)
        return [next_stage] if next_stage else []

    async def add_file_at(self, file_hash: str, entry_queue: QueueType) -> bool:
        """Add a file to the pipeline at a specific queue."""
        return await self.queues[entry_queue].put(file_hash)

    async def route_to_next(
        self, file_hash: str, from_queue: QueueType, generation: int | None = None
    ) -> None:
        """Route a file to the next queue(s) in the pipeline.

        `generation` is the one the item was taken under; after a Stop the
        item goes no further.
        """
        if generation is not None and generation != self.generation:
            return
        for next_queue_type in self.get_next_queues(from_queue):
            await self.queues[next_queue_type].put(file_hash)

    def add_error(self, queue: str, file_hash: str, file_path: str | None, error: str) -> None:
        """Add an error to the error log."""
        self.error_log.append({
            # Naive UTC, matching the format the status page has always shown.
            "timestamp": datetime.now(UTC).replace(tzinfo=None).isoformat(),
            "queue": queue,
            "file_hash": file_hash,
            "file_path": file_path,
            "error": error[:200],
        })
        if len(self.error_log) > ERROR_LOG_SIZE:
            del self.error_log[:-ERROR_LOG_SIZE]

    def get_queue_info(self) -> dict[str, dict]:
        """Get detailed queue information for each queue type."""
        return {
            qtype.value: {
                "queue_type": qtype.value,
                "pending": queue.qsize(),
                "processing": 1 if queue.current_file_hash else 0,
                "current_file_hash": queue.current_file_hash,
                "current_file_path": queue.current_file_path,
            }
            for qtype, queue in self.queues.items()
        }

    def get_queue_sizes(self) -> dict[str, int]:
        """Get current queue sizes (legacy format for compatibility)."""
        return {qtype.value: queue.qsize() for qtype, queue in self.queues.items()}

    async def request_batch(self) -> None:
        """Have the batch step (face clustering, duplicates, events) rerun,
        e.g. after photos left the index without passing through a stage."""
        await self.queues[QueueType.EVENTS].put("")

    def stop_and_drain(self) -> None:
        """Stop the running scan and drop all queued work.

        Workers keep running: what they hold finishes its current stage and
        goes no further, and anything queued afterwards (Resume, a rescan,
        the watcher) is processed as usual.
        """
        self._stop_requested = True
        self.generation += 1
        for queue in self.queues.values():
            queue.drain()

    def begin_work(self) -> int:
        """Mark the start of a scan or resume. Returns the generation a scan
        compares against to notice a later Stop."""
        self._stop_requested = False
        return self.generation


# Global pipeline instance
pipeline = Pipeline()
