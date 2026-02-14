"""Scan control and status API endpoints."""

import asyncio

from fastapi import APIRouter

from backend.app.workers.pipeline import run_initial_scan, resume_incomplete_processing
from backend.app.workers.queues import pipeline
from backend.app.database import async_session
from backend.app.models import Photo, PhotoPath, PhotoHash, Face, Person, Tag, PhotoTag, Event, EventPhoto, Caption, DuplicateGroup, DuplicateMember

router = APIRouter(prefix="/api/scan", tags=["scan"])

# Simple scan state
_is_scanning = False


@router.get("/status")
async def get_scan_status():
    """Get current scan/processing status."""
    queue_sizes = pipeline.get_queue_sizes()
    return {
        "is_scanning": _is_scanning,
        "queue_sizes": queue_sizes,
    }


@router.post("/trigger")
async def trigger_scan():
    """Manually trigger a rescan of the photos directory."""
    global _is_scanning
    if _is_scanning:
        return {"status": "already_scanning"}

    _is_scanning = True
    try:
        await run_initial_scan()
    finally:
        _is_scanning = False

    return {"status": "scan_started"}


@router.post("/stop")
async def stop_pipeline():
    """Stop all pipeline activity."""
    global _is_scanning
    _is_scanning = False
    pipeline._stop_requested = True

    # Drain queues
    for qtype in pipeline.queues:
        queue = pipeline.queues[qtype]
        while not queue.empty():
            try:
                queue.queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    return {"status": "stopped"}


@router.post("/clear-index")
async def clear_index():
    """Clear all indexed data and reset the pipeline."""
    global _is_scanning
    if _is_scanning:
        return {"status": "cannot_clear_while_scanning"}

    async with async_session() as session:
        # Delete all related data in correct order
        await session.execute(DuplicateMember.__table__.delete())
        await session.execute(DuplicateGroup.__table__.delete())
        await session.execute(EventPhoto.__table__.delete())
        await session.execute(Event.__table__.delete())
        await session.execute(PhotoTag.__table__.delete())
        await session.execute(Tag.__table__.delete())
        await session.execute(Face.__table__.delete())
        await session.execute(Person.__table__.delete())
        await session.execute(Caption.__table__.delete())
        await session.execute(PhotoHash.__table__.delete())
        await session.execute(PhotoPath.__table__.delete())
        await session.execute(Photo.__table__.delete())
        await session.commit()

    return {"status": "index_cleared"}


@router.post("/resume")
async def resume_processing():
    """Resume processing for incomplete photos."""
    count = await resume_incomplete_processing()
    return {"status": "resumed", "queued": count}