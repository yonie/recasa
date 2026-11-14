"""Scan control and status API endpoints."""

import asyncio
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks
from sqlalchemy import delete, update

from backend.app.database import async_session
from backend.app.models import (
    Caption,
    DuplicateGroup,
    DuplicateMember,
    Event,
    EventPhoto,
    Face,
    Person,
    Photo,
    PhotoHash,
    PhotoPath,
    PhotoTag,
    StageFailure,
    Tag,
)
from backend.app.workers.pipeline import resume_incomplete_processing, run_initial_scan
from backend.app.workers.queues import pipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scan", tags=["scan"])

# Scan state
_is_scanning = False
_scan_progress = {"current": 0, "total": 0, "current_file": None}
_last_scan_at: str | None = None  # ISO timestamp of last completed scan/sweep
_last_scan_stats: dict | None = None


@router.get("/status")
async def get_scan_status():
    """Get current scan/processing status."""
    queue_sizes = pipeline.get_queue_sizes()
    return {
        "is_scanning": _is_scanning,
        "scan_progress": _scan_progress,
        "queue_sizes": queue_sizes,
    }


async def _run_scan_background(fast: bool = False):
    """Run scan in background and queue new photos."""
    global _is_scanning, _scan_progress, _last_scan_at, _last_scan_stats

    _is_scanning = True
    _scan_progress = {"current": 0, "total": 0, "current_file": None}

    try:
        stats = await run_initial_scan(fast=fast)
        _last_scan_at = datetime.now(UTC).isoformat()
        _last_scan_stats = {
            k: v for k, v in stats.items() if k in ("total", "new", "updated", "errors")
        }
    finally:
        _is_scanning = False
        _scan_progress = {"current": 0, "total": 0, "current_file": None}


async def periodic_rescan_loop(interval: int) -> None:
    """Sweep the photos directory for changes every `interval` seconds.

    This is the reliable fallback for the inotify watcher: file events don't
    cross Docker bind mounts on Windows/macOS hosts, so without this loop new
    photos are only picked up on a manual rescan. The scanner skips unchanged
    files on a size+mtime check, so an empty sweep is cheap. Sleeps *between*
    sweeps, so a slow sweep can never overlap the next one.
    """
    logger.info("Periodic rescan enabled: every %ds", interval)
    while True:
        await asyncio.sleep(interval)
        if _is_scanning:
            continue
        try:
            await _run_scan_background(fast=True)
        except Exception:
            logger.exception("Periodic rescan failed; will retry next interval")


@router.post("/trigger")
async def trigger_scan(background_tasks: BackgroundTasks):
    """Trigger a rescan of the photos directory (non-blocking)."""
    if _is_scanning:
        return {"status": "already_scanning", "progress": _scan_progress}

    background_tasks.add_task(_run_scan_background)
    return {"status": "scan_started"}


@router.post("/stop")
async def stop_pipeline():
    """Stop all pipeline activity."""
    global _is_scanning
    _is_scanning = False
    pipeline.stop_and_drain()
    return {"status": "stopped"}


@router.post("/clear-index")
async def clear_index():
    """Clear all indexed data and reset the pipeline."""
    if _is_scanning:
        return {"status": "cannot_clear_while_scanning"}

    async with async_session() as session:
        # Delete all related data in correct order
        await session.execute(delete(DuplicateMember))
        await session.execute(delete(DuplicateGroup))
        await session.execute(delete(EventPhoto))
        await session.execute(delete(Event))
        await session.execute(delete(PhotoTag))
        await session.execute(delete(Tag))
        await session.execute(delete(Face))
        await session.execute(delete(Person))
        await session.execute(delete(Caption))
        await session.execute(delete(PhotoHash))
        await session.execute(delete(StageFailure))
        await session.execute(delete(PhotoPath))
        await session.execute(delete(Photo))
        await session.commit()

    return {"status": "index_cleared"}


@router.post("/clear-stage/{stage}")
async def clear_stage(stage: str):
    """Clear data for a single pipeline stage, allowing it to be re-processed."""
    if _is_scanning:
        return {"status": "cannot_clear_while_scanning"}

    async with async_session() as session:
        if stage == "geocoding":
            await session.execute(
                update(Photo).where(Photo.location_city.is_not(None)).values(
                    location_country=None, location_city=None, location_address=None,
                )
            )
        elif stage == "hashing":
            await session.execute(delete(DuplicateMember))
            await session.execute(delete(DuplicateGroup))
            await session.execute(delete(PhotoHash))
        elif stage == "faces":
            await session.execute(delete(Face))
            await session.execute(delete(Person))
        elif stage == "captioning":
            await session.execute(delete(Caption))
        elif stage == "events":
            await session.execute(delete(EventPhoto))
            await session.execute(delete(Event))
        else:
            return {"status": "unsupported_stage", "stage": stage}

        # A rebuild is also the retry path for permanently-failed photos.
        await session.execute(
            delete(StageFailure).where(StageFailure.stage == stage)
        )
        await session.commit()

    return {"status": "stage_cleared", "stage": stage}


@router.post("/resume")
async def resume_processing():
    """Resume processing for incomplete photos."""
    count = await resume_incomplete_processing()
    return {"status": "resumed", "queued": count}