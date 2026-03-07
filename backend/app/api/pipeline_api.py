"""Pipeline status and statistics API endpoints."""

import asyncio
from pathlib import Path
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_session
from backend.app.models import Photo, PhotoHash, Face, Caption, Event
from backend.app.workers.queues import pipeline, QueueType
from backend.app.workers.worker import pipeline_logs
from backend.app.config import settings

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


@router.get("/status")
async def get_pipeline_status():
    """Get current pipeline status."""
    queue_info = pipeline.get_queue_info()
    return {
        "running": pipeline.is_running,
        "stop_requested": pipeline._stop_requested,
        "state": "processing" if pipeline.is_running else "idle",
        "scan_progress": None,
        "processing_progress": None,
        "completion_summary": None,
        "error_log": pipeline.error_log[-20:],
        "error_count": len(pipeline.error_log),
        "queues": queue_info,
    }


@router.get("/processing-stats")
async def get_processing_stats(session: AsyncSession = Depends(get_session)):
    """Get photo processing completion stats from the database.
    
    For each stage, returns:
    - status: "pending" | "processing" | "done" | "disabled"
    - queued: items waiting in queue (0 if disabled or done)
    - completed: items processed (total - queued)
    - total: total items to process for this stage
    - enabled: whether the stage is enabled
    """
    total = await session.execute(select(func.count(Photo.file_hash)))
    total_photos = total.scalar() or 0

    # Get queue sizes
    queue_sizes = pipeline.get_queue_sizes()

    # Helper to determine stage status
    def get_stage_status(enabled: bool, queued: int) -> str:
        if not enabled:
            return "disabled"
        if queued > 0:
            return "processing"
        return "done"

    # Calculate completed for each stage: completed = total - queued
    # When queue is empty, all photos have been processed
    
    # EXIF: always enabled, queue-based
    exif_queued = queue_sizes.get("exif", 0)
    exif_completed = total_photos - exif_queued if exif_queued > 0 else total_photos

    # Geocoding: only photos with GPS are eligible
    geo_queued = queue_sizes.get("geocoding", 0)
    geo_eligible = await session.execute(
        select(func.count(Photo.file_hash)).where(Photo.gps_latitude.is_not(None))
    )
    geo_total = geo_eligible.scalar() or 0
    geo_completed = geo_total - geo_queued if geo_queued > 0 else geo_total

    # Thumbnails: queue-based
    thumbs_queued = queue_sizes.get("thumbnails", 0)
    thumbs_completed = total_photos - thumbs_queued if thumbs_queued > 0 else total_photos

    # Motion Photos: always enabled, queue-based
    motion_queued = queue_sizes.get("motion_photos", 0)
    motion_completed = total_photos - motion_queued if motion_queued > 0 else total_photos

    # Hashing: queue-based
    hash_queued = queue_sizes.get("hashing", 0)
    hash_completed = total_photos - hash_queued if hash_queued > 0 else total_photos

    # Faces: queue-based completion
    faces_queued = queue_sizes.get("faces", 0)
    faces_completed = total_photos - faces_queued if faces_queued > 0 else total_photos
    # Count photos with actual faces (encoding IS NOT NULL), exclude markers
    faces_with_detected = (await session.execute(
        select(func.count(func.distinct(Face.file_hash))).where(Face.encoding.is_not(None))
    )).scalar() or 0

    # Captioning: queue-based completion
    caption_queued = queue_sizes.get("captioning", 0)
    caption_completed = total_photos - caption_queued if caption_queued > 0 else total_photos
    # Count photos with actual captions (caption IS NOT NULL), exclude markers
    captions_generated = (await session.execute(
        select(func.count(Caption.file_hash)).where(Caption.caption.is_not(None))
    )).scalar() or 0

    # Events: batch-processed, not per-photo. Show event count.
    events_done = await session.execute(select(func.count(Event.event_id)))
    event_count = events_done.scalar() or 0

    return {
        "total_photos": total_photos,
        "stages": {
            "discovery": {
                "status": "done",
                "queued": 0,
                "completed": total_photos,
                "total": total_photos,
                "enabled": True,
            },
            "exif": {
                "status": get_stage_status(True, exif_queued),
                "queued": exif_queued,
                "completed": exif_completed,
                "total": total_photos,
                "enabled": True,
            },
            "geocoding": {
                "status": get_stage_status(settings.ENABLE_GEOCODING, geo_queued),
                "queued": geo_queued if settings.ENABLE_GEOCODING else 0,
                "completed": geo_completed,
                "total": geo_total,
                "enabled": settings.ENABLE_GEOCODING,
            },
            "thumbnails": {
                "status": get_stage_status(True, thumbs_queued),
                "queued": thumbs_queued,
                "completed": thumbs_completed,
                "total": total_photos,
                "enabled": True,
            },
            "motion_photos": {
                "status": get_stage_status(True, motion_queued),
                "queued": motion_queued,
                "completed": motion_completed,
                "total": total_photos,
                "enabled": True,
            },
            "hashing": {
                "status": get_stage_status(True, hash_queued),
                "queued": hash_queued,
                "completed": hash_completed,
                "total": total_photos,
                "enabled": True,
            },
            "faces": {
                "status": get_stage_status(settings.ENABLE_FACE_DETECTION, faces_queued),
                "queued": faces_queued if settings.ENABLE_FACE_DETECTION else 0,
                "completed": faces_completed,
                "total": total_photos,
                "enabled": settings.ENABLE_FACE_DETECTION,
                "faces_found": faces_with_detected,
            },
            "captioning": {
                "status": get_stage_status(settings.ENABLE_CAPTIONING, caption_queued),
                "queued": caption_queued if settings.ENABLE_CAPTIONING else 0,
                "completed": caption_completed,
                "total": total_photos,
                "enabled": settings.ENABLE_CAPTIONING,
                "captions_generated": captions_generated,
            },
            "events": {
                "status": "done" if event_count > 0 else "pending",
                "queued": 0,
                "completed": event_count,
                "total": 1,  # Events is a batch operation, just need to know if done
                "enabled": True,
                "count": event_count,
            },
        },
    }


@router.get("/logs")
async def get_pipeline_logs():
    """Get recent pipeline processing logs."""
    return list(pipeline_logs)


@router.get("/queues")
async def get_queue_status():
    """Get current queue sizes."""
    return pipeline.get_queue_sizes()


@router.post("/stop")
async def stop_pipeline():
    """Stop all pipeline activity."""
    pipeline._stop_requested = True
    
    # Drain queues
    for qtype in QueueType:
        queue = pipeline.queues[qtype]
        while not queue.empty():
            try:
                queue.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
    
    return {"status": "stopped"}


@router.websocket("/ws")
async def pipeline_websocket(websocket: WebSocket):
    """WebSocket endpoint for real-time pipeline statistics."""
    await websocket.accept()

    try:
        while True:
            queue_info = pipeline.get_queue_info()
            status = {
                "running": pipeline.is_running,
                "stop_requested": pipeline._stop_requested,
                "state": "processing" if pipeline.is_running else "idle",
                "scan_progress": None,
                "processing_progress": None,
                "completion_summary": None,
                "error_log": pipeline.error_log[-20:],
                "error_count": len(pipeline.error_log),
                "queues": queue_info,
            }
            await websocket.send_json(status)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass