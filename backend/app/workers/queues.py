"""Pipeline queue system for parallel photo processing.

Architecture:
  Discovery → EXIF → Geocoding → Thumbnail → Hashing → Faces → Captioning → Events
                        ↓
                    Motion Photos

Each queue checks if processing is needed before processing to handle restarts gracefully.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class QueueType(Enum):
    DISCOVERY = "discovery"
    EXIF = "exif"
    GEOCODING = "geocoding"
    THUMBNAILS = "thumbnails"
    MOTION_PHOTOS = "motion_photos"
    HASHING = "hashing"
    FACES = "faces"
    CAPTIONING = "captioning"
    EVENTS = "events"


@dataclass
class QueueStats:
    """Statistics for a single queue."""
    queue_type: QueueType
    pending: int = 0
    processing: int = 0
    completed_total: int = 0
    skipped_total: int = 0
    failed_total: int = 0
    last_processed_at: datetime | None = None
    last_file_hash: str | None = None
    current_file_hash: str | None = None
    current_file_path: str | None = None


class ProcessingQueue:
    """A queue for processing photos through a specific stage.

    Each queue tracks which files it has processed to avoid re-processing on restart.
    """

    def __init__(self, queue_type: QueueType, max_size: int = 1000):
        self.queue_type = queue_type
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=max_size)
        self.stats = QueueStats(queue_type=queue_type)
        self._processing: set[str] = set()
        self._processed: set[str] = set()  # Track files processed by this queue
        self._lock = asyncio.Lock()

    async def put(self, file_hash: str, timeout: float = 5.0) -> bool:
        """Add a file hash to the queue. Returns True if successful, False if already processed."""
        async with self._lock:
            if file_hash in self._processed:
                self.stats.skipped_total += 1
                return False
            if file_hash in self._processing or self.queue.qsize() >= self.queue.maxsize:
                return False

        try:
            await asyncio.wait_for(self.queue.put(file_hash), timeout=timeout)
            async with self._lock:
                self.stats.pending += 1
            return True
        except asyncio.TimeoutError:
            logger.warning(f"Queue {self.queue_type.value} is full, dropping file")
            return False

    async def get(self) -> str:
        """Get the next file hash from the queue."""
        file_hash = await self.queue.get()
        async with self._lock:
            self.stats.pending -= 1
            self.stats.processing += 1
            self._processing.add(file_hash)
        return file_hash

    async def mark_processing(self, file_hash: str, file_path: str | None = None):
        """Mark a file as currently being processed."""
        async with self._lock:
            self.stats.current_file_hash = file_hash
            self.stats.current_file_path = file_path

    async def mark_completed(self, file_hash: str):
        """Mark a file as completed and skip future processing."""
        async with self._lock:
            self.stats.processing -= 1
            self.stats.completed_total += 1
            self.stats.last_processed_at = datetime.utcnow()
            self.stats.last_file_hash = file_hash
            self._processing.discard(file_hash)
            self._processed.add(file_hash)
            if file_hash == self.stats.current_file_hash:
                self.stats.current_file_hash = None
                self.stats.current_file_path = None

    async def mark_failed(self, file_hash: str):
        """Mark a file as failed."""
        async with self._lock:
            self.stats.processing -= 1
            self.stats.failed_total += 1
            self._processing.discard(file_hash)
            self._processed.add(file_hash)
            if file_hash == self.stats.current_file_hash:
                self.stats.current_file_hash = None
                self.stats.current_file_path = None

    def is_processed(self, file_hash: str) -> bool:
        """Check if a file has already been processed by this queue."""
        return file_hash in self._processed

    def is_queued(self, file_hash: str) -> bool:
        """Check if a file is already in the queue or processing."""
        return file_hash in self._processing or file_hash in self._processed

    def get_stats(self) -> dict[str, Any]:
        """Get queue statistics as a dict."""
        return {
            "queue_type": self.queue_type.value,
            "pending": max(self.stats.pending, 0),
            "processing": max(self.stats.processing, 0),
            "completed_total": self.stats.completed_total,
            "skipped_total": self.stats.skipped_total,
            "failed_total": self.stats.failed_total,
            "last_processed_at": self.stats.last_processed_at.isoformat() if self.stats.last_processed_at else None,
            "last_file_hash": self.stats.last_file_hash,
            "current_file_hash": self.stats.current_file_hash,
            "current_file_path": self.stats.current_file_path,
        }


class Pipeline:
    """Orchestrates the photo processing pipeline with parallel queues.

    Each queue checks if processing is needed before processing to handle restarts gracefully.
    """

    def __init__(self):
        self.queues: dict[QueueType, ProcessingQueue] = {}
        self.workers: list[asyncio.Task] = []
        self.is_running = False
        self._start_time: datetime | None = None
        self._completed_time: datetime | None = None
        self._total_discovered = 0
        self.error_log: list[dict] = []  # List of {timestamp, queue, file_hash, file_path, error}

        # Create queues
        for qtype in QueueType:
            self.queues[qtype] = ProcessingQueue(qtype)

        # Define pipeline flow - sequential per file
        # Each file goes through all steps in order
        self._flow: dict[QueueType, list[QueueType]] = {
            QueueType.DISCOVERY: [QueueType.EXIF],
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

    async def add_file(self, file_hash: str, file_path: str) -> bool:
        """Add a newly discovered file to the pipeline (starts at DISCOVERY)."""
        self._total_discovered += 1
        return await self.queues[QueueType.DISCOVERY].put(file_hash)

    async def add_file_at(self, file_hash: str, entry_queue: QueueType) -> bool:
        """Add a file to the pipeline at a specific queue (for partial processing)."""
        self._total_discovered += 1
        return await self.queues[entry_queue].put(file_hash)

    def is_queued(self, queue_type: QueueType, file_hash: str) -> bool:
        """Check if a file is already queued or processed in a specific queue."""
        return self.queues[queue_type].is_queued(file_hash)

    async def route_to_next(self, file_hash: str, from_queue: QueueType):
        """Route a file to the next queue(s) in the pipeline."""
        next_queues = self.get_next_queues(from_queue)
        for next_queue_type in next_queues:
            await self.queues[next_queue_type].put(file_hash)

    def get_pipeline_stats(self) -> dict[str, Any]:
        """Get full pipeline statistics with unified status.

        Returns a single 'state' field that tells the full story:
        - idle: nothing happening, waiting for user action
        - scanning: discovering files on disk
        - processing: pipeline workers are actively processing
        - done: everything complete
        """
        now = datetime.utcnow()

        # Check if scanning (discovery phase)
        from backend.app.workers.pipeline import scan_state
        is_scanning = scan_state.is_scanning

        # Check if processing (workers active)
        total_pending = sum(max(q.stats.pending, 0) for q in self.queues.values())
        total_processing = sum(max(q.stats.processing, 0) for q in self.queues.values())
        is_processing = total_pending > 0 or total_processing > 0

        # Determine unified state
        if is_scanning:
            state = "scanning"
        elif is_processing:
            state = "processing"
        elif self._total_discovered > 0 and total_pending == 0 and total_processing == 0:
            state = "done"
        else:
            state = "idle"

        # Track completion time
        if state in ("done", "idle") and self._total_discovered > 0:
            if self._completed_time is None:
                self._completed_time = now
        else:
            self._completed_time = None

        # Compute elapsed time
        if self._start_time is None:
            elapsed_seconds = 0.0
        elif self._completed_time is not None:
            elapsed_seconds = (self._completed_time - self._start_time).total_seconds()
        else:
            elapsed_seconds = (now - self._start_time).total_seconds()

        # Compute completion stats
        total_files_needing_work = sum(
            q.stats.completed_total + q.stats.pending + q.stats.processing + q.stats.failed_total
            for q in self.queues.values()
            if q.queue_type != QueueType.EVENTS
        ) or 1

        return {
            # Unified status - single source of truth
            "state": state,

            # Scan progress (only relevant during 'scanning')
            "scan_progress": {
                "is_scanning": is_scanning,
                "total_files": scan_state.total_files,
                "scanned_files": scan_state.processed_files,
                "current_directory": scan_state.current_file,
            } if is_scanning else None,

            # Processing progress (only relevant during 'processing')
            "processing_progress": {
                "files_queued": total_pending,
                "files_processing": total_processing,
                "elapsed_seconds": elapsed_seconds,
            } if state == "processing" else None,

            # Completion summary (only relevant during 'done')
            "completion_summary": {
                "files_processed": self.queues[QueueType.EVENTS].stats.completed_total,
                "elapsed_seconds": elapsed_seconds,
                "completed_at": self._completed_time.isoformat() if self._completed_time else None,
            } if state == "done" else None,

            # Error tracking (always available)
            "error_log": self.error_log[-50:],
            "error_count": len([e for e in self.error_log]),

            # Detailed queue stats (for debugging/details view)
            "queues": {
                qtype.value: queue.get_stats()
                for qtype, queue in self.queues.items()
            },
        }

    def add_error(self, queue: str, file_hash: str, file_path: str | None, error: str):
        """Add an error to the error log."""
        self.error_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "queue": queue,
            "file_hash": file_hash,
            "file_path": file_path,
            "error": error[:200],  # Truncate long errors
        })
        # Keep only last 100 errors
        if len(self.error_log) > 100:
            self.error_log = self.error_log[-100:]


# Global pipeline instance
pipeline = Pipeline()
