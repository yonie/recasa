"""Pipeline status and statistics API endpoints."""

import asyncio
from pathlib import Path
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_session
from backend.app.models import Photo, PhotoHash, Face, Caption, Event
from backend.app.workers.queues import pipeline, QueueType
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
    - completed: items successfully processed
    - total: total items to process for this stage
    - enabled: whether the stage is enabled
    """
    total = await session.execute(select(func.count(Photo.file_hash)))
    total_photos = total.scalar() or 0

    # Get queue sizes
    queue_sizes = pipeline.get_queue_sizes()

    # Helper to determine stage status
    def get_stage_status(enabled: bool, queued: int, completed: int, total: int) -> str:
        if not enabled:
            return "disabled"
        if queued > 0:
            return "processing"
        # If queue is empty, stage is done (some may have failed, but all attempts complete)
        if queued == 0:
            return "done"
        return "pending"

    # EXIF: camera_make OR date_taken exists
    exif_done = await session.execute(
        select(func.count(Photo.file_hash)).where(
            Photo.camera_make.is_not(None) | Photo.date_taken.is_not(None)
        )
    )
    exif_completed = exif_done.scalar() or 0

    # Geocoding: only photos with GPS coordinates are eligible
    geo_eligible = await session.execute(
        select(func.count(Photo.file_hash)).where(Photo.gps_latitude.is_not(None))
    )
    geo_total = geo_eligible.scalar() or 0
    geo_done = await session.execute(
        select(func.count(Photo.file_hash)).where(Photo.location_city.is_not(None))
    )
    geo_completed = geo_done.scalar() or 0

    # Thumbnails: count files on disk
    hashes_result = await session.execute(select(Photo.file_hash))
    all_hashes = set(hashes_result.scalars().all())
    
    def count_thumbnails_for_photos(hashes: set) -> int:
        thumbs_dir = settings.thumbnails_dir
        if not thumbs_dir.exists():
            return 0
        count = 0
        for subdir in thumbs_dir.iterdir():
            if subdir.is_dir() and len(subdir.name) == 2:
                for f in subdir.iterdir():
                    if f.name.endswith("_200.webp"):
                        file_hash = f.name.split("_200.webp")[0]
                        if file_hash in hashes:
                            count += 1
        return count

    thumbs_completed = await asyncio.to_thread(count_thumbnails_for_photos, all_hashes)

    # Hashing: PhotoHash records exist
    hash_done = await session.execute(select(func.count(PhotoHash.file_hash)))
    hash_completed = hash_done.scalar() or 0

    # Motion Photos: Stage is always enabled. If queue empty, all processed.
    # motion_photo=True means the photo IS a motion photo (Live Photo), not that it was checked.
    # All photos are checked - completed = total when queue is empty.
    motion_queue_empty = pipeline.queues[QueueType.MOTION_PHOTOS].empty()
    motion_completed = total_photos if motion_queue_empty else 0

    # Faces: distinct file_hashes with Face records = photos with faces detected
    # But "processed" means we CHECKED all photos, not just found faces
    faces_done = await session.execute(select(func.count(func.distinct(Face.file_hash))))
    faces_with_detected = faces_done.scalar() or 0
    
    # All photos go through faces queue. If queue is empty and enabled, all were processed.
    # If disabled, show what we have.
    faces_queued = queue_sizes.get("faces", 0)
    faces_completed = total_photos if (settings.ENABLE_FACE_DETECTION and faces_queued == 0) else faces_with_detected

    # Captioning: Caption records exist
    caption_done = await session.execute(select(func.count(Caption.file_hash)))
    caption_completed = caption_done.scalar() or 0

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
                "status": get_stage_status(True, queue_sizes.get("exif", 0), exif_completed, total_photos),
                "queued": queue_sizes.get("exif", 0),
                "completed": exif_completed,
                "total": total_photos,
                "enabled": True,
            },
            "geocoding": {
                "status": get_stage_status(settings.ENABLE_GEOCODING, queue_sizes.get("geocoding", 0), geo_completed, geo_total),
                "queued": queue_sizes.get("geocoding", 0) if settings.ENABLE_GEOCODING else 0,
                "completed": geo_completed,
                "total": geo_total,
                "enabled": settings.ENABLE_GEOCODING,
            },
            "thumbnails": {
                "status": get_stage_status(True, queue_sizes.get("thumbnails", 0), thumbs_completed, total_photos),
                "queued": queue_sizes.get("thumbnails", 0),
                "completed": thumbs_completed,
                "total": total_photos,
                "enabled": True,
            },
            "motion_photos": {
                "status": "done",  # Motion photos is always enabled
                "queued": 0,
                "completed": motion_completed,
                "total": total_photos,
                "enabled": True,
            },
            "hashing": {
                "status": get_stage_status(True, queue_sizes.get("hashing", 0), hash_completed, total_photos),
                "queued": queue_sizes.get("hashing", 0),
                "completed": hash_completed,
                "total": total_photos,
                "enabled": True,
            },
            "faces": {
                "status": get_stage_status(settings.ENABLE_FACE_DETECTION, faces_queued, faces_completed, total_photos),
                "queued": faces_queued if settings.ENABLE_FACE_DETECTION else 0,
                "completed": faces_completed,
                "total": total_photos,
                "enabled": settings.ENABLE_FACE_DETECTION,
                "faces_found": faces_with_detected,
            },
            "captioning": {
                "status": get_stage_status(settings.ENABLE_CAPTIONING, queue_sizes.get("captioning", 0), caption_completed, total_photos),
                "queued": queue_sizes.get("captioning", 0) if settings.ENABLE_CAPTIONING else 0,
                "completed": caption_completed,
                "total": total_photos,
                "enabled": settings.ENABLE_CAPTIONING,
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