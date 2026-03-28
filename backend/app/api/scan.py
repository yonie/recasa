"""Scan control and status API endpoints."""

from fastapi import APIRouter, BackgroundTasks

from backend.app.workers.pipeline import run_initial_scan, resume_incomplete_processing
from backend.app.workers.queues import pipeline
from backend.app.database import async_session
from backend.app.models import Photo, PhotoPath, PhotoHash, Face, Person, Tag, PhotoTag, Event, EventPhoto, Caption, DuplicateGroup, DuplicateMember

router = APIRouter(prefix="/api/scan", tags=["scan"])

# Scan state
_is_scanning = False
_scan_progress = {"current": 0, "total": 0, "current_file": None}


@router.get("/status")
async def get_scan_status():
    """Get current scan/processing status."""
    queue_sizes = pipeline.get_queue_sizes()
    return {
        "is_scanning": _is_scanning,
        "scan_progress": _scan_progress,
        "queue_sizes": queue_sizes,
    }


async def _run_scan_background():
    """Run scan in background and queue new photos."""
    global _is_scanning, _scan_progress
    
    _is_scanning = True
    _scan_progress = {"current": 0, "total": 0, "current_file": None}
    
    try:
        await run_initial_scan()
    finally:
        _is_scanning = False
        _scan_progress = {"current": 0, "total": 0, "current_file": None}


@router.post("/trigger")
async def trigger_scan(background_tasks: BackgroundTasks):
    """Trigger a rescan of the photos directory (non-blocking)."""
    global _is_scanning
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


@router.post("/clear-stage/{stage}")
async def clear_stage(stage: str):
    """Clear data for a single pipeline stage, allowing it to be re-processed."""
    global _is_scanning
    if _is_scanning:
        return {"status": "cannot_clear_while_scanning"}

    from sqlalchemy import update

    async with async_session() as session:
        if stage == "geocoding":
            await session.execute(
                update(Photo).where(Photo.location_city.is_not(None)).values(
                    location_country=None, location_city=None, location_address=None,
                )
            )
        elif stage == "hashing":
            await session.execute(DuplicateMember.__table__.delete())
            await session.execute(DuplicateGroup.__table__.delete())
            await session.execute(PhotoHash.__table__.delete())
        elif stage == "faces":
            await session.execute(Face.__table__.delete())
            await session.execute(Person.__table__.delete())
        elif stage == "captioning":
            await session.execute(Caption.__table__.delete())
        elif stage == "events":
            await session.execute(EventPhoto.__table__.delete())
            await session.execute(Event.__table__.delete())
        else:
            return {"status": "unsupported_stage", "stage": stage}

        await session.commit()

    return {"status": "stage_cleared", "stage": stage}


@router.post("/resume")
async def resume_processing():
    """Resume processing for incomplete photos."""
    count = await resume_incomplete_processing()
    return {"status": "resumed", "queued": count}