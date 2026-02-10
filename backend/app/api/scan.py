"""Scan control and status API endpoints."""

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.app.schemas.photo import ScanStatus
from backend.app.workers.pipeline import run_initial_scan, scan_state
from backend.app.workers.queues import pipeline, QueueType
from backend.app.database import async_session
from backend.app.models import Photo, PhotoPath, PhotoHash, Face, Person, Tag, PhotoTag, Event, EventPhoto, Caption, DuplicateGroup, DuplicateMember

router = APIRouter(prefix="/api/scan", tags=["scan"])


@router.get("/status", response_model=ScanStatus)
async def get_scan_status():
    """Get current scan/processing status."""
    return ScanStatus(**scan_state.to_dict())


@router.post("/trigger")
async def trigger_scan():
    """Manually trigger a rescan of the photos directory."""
    if scan_state.is_scanning:
        return {"status": "already_scanning"}

    asyncio.create_task(run_initial_scan())
    return {"status": "scan_started"}


@router.post("/cancel")
async def cancel_scan():
    """Cancel the currently running scan."""
    if not scan_state.is_scanning:
        return {"status": "not_scanning"}

    scan_state.cancel_requested = True
    return {"status": "cancel_requested"}


@router.post("/clear-index")
async def clear_index():
    """Clear all indexed data and reset the pipeline. Use with caution!"""
    if scan_state.is_scanning:
        return {"status": "cannot_clear_while_scanning"}

    async with async_session() as session:
        # Delete all related data in correct order (respecting foreign keys)
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

    # Reset pipeline queues
    for qtype in QueueType:
        queue = pipeline.queues[qtype]
        queue._processed.clear()
        queue._processing.clear()
        queue.stats.completed_total = 0
        queue.stats.skipped_total = 0
        queue.stats.failed_total = 0
        queue.stats.pending = 0
        queue.stats.processing = 0

    pipeline._total_discovered = 0

    return {"status": "index_cleared"}


@router.websocket("/ws")
async def scan_websocket(websocket: WebSocket):
    """WebSocket endpoint for real-time scan progress updates."""
    await websocket.accept()

    queue = scan_state.add_listener()

    try:
        # Send initial state
        await websocket.send_text(json.dumps(scan_state.to_dict()))

        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_text(json.dumps(msg))
            except asyncio.TimeoutError:
                # Send heartbeat
                await websocket.send_text(json.dumps({"heartbeat": True}))
    except WebSocketDisconnect:
        pass
    finally:
        scan_state.remove_listener(queue)
