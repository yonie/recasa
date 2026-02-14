"""Pipeline status and statistics API endpoints."""

import asyncio
from pathlib import Path
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_session
from backend.app.models import Photo, PhotoHash, Face, Caption
from backend.app.workers.queues import pipeline, QueueType
from backend.app.config import settings

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


@router.get("/status")
async def get_pipeline_status():
    """Get current pipeline status."""
    queue_sizes = pipeline.get_queue_sizes()
    return {
        "running": pipeline.is_running,
        "stop_requested": pipeline._stop_requested,
        "queues": queue_sizes,
        "error_log": pipeline.error_log[-20:],
    }


@router.get("/processing-stats")
async def get_processing_stats(session: AsyncSession = Depends(get_session)):
    """Get photo processing completion stats from the database."""
    total = await session.execute(select(func.count(Photo.file_hash)))
    total_photos = total.scalar() or 0

    # Get all file hashes
    hashes_result = await session.execute(select(Photo.file_hash))
    all_hashes = set(hashes_result.scalars().all())

    # EXIF: camera_make OR date_taken exists
    exif_done = await session.execute(
        select(func.count(Photo.file_hash)).where(
            Photo.camera_make.is_not(None) | Photo.date_taken.is_not(None)
        )
    )
    exif_count = exif_done.scalar() or 0

    # Geocoding: location_city exists
    geo_done = await session.execute(
        select(func.count(Photo.file_hash)).where(Photo.location_city.is_not(None))
    )
    geo_count = geo_done.scalar() or 0

    # Thumbnails: count files on disk that match our photos
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

    thumbs_count = await asyncio.to_thread(count_thumbnails_for_photos, all_hashes)

    # Hashing: PhotoHash records exist
    hash_done = await session.execute(select(func.count(PhotoHash.file_hash)))
    hash_count = hash_done.scalar() or 0

    # Faces: Face records exist
    faces_done = await session.execute(select(func.count(func.distinct(Face.file_hash))))
    faces_count = faces_done.scalar() or 0

    # Captioning: Caption records exist
    caption_done = await session.execute(select(func.count(Caption.file_hash)))
    caption_count = caption_done.scalar() or 0

    return {
        "total_photos": total_photos,
        "stages": {
            "exif": {"completed": exif_count, "total": total_photos, "enabled": True},
            "geocoding": {"completed": geo_count, "total": total_photos, "enabled": settings.ENABLE_GEOCODING},
            "thumbnails": {"completed": thumbs_count, "total": total_photos, "enabled": True},
            "hashing": {"completed": hash_count, "total": total_photos, "enabled": True},
            "faces": {"completed": faces_count, "total": total_photos, "enabled": settings.ENABLE_FACE_DETECTION},
            "captioning": {"completed": caption_count, "total": total_photos, "enabled": settings.ENABLE_CAPTIONING},
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


@router.post("/start")
async def start_pipeline():
    """Resume pipeline processing by re-queuing incomplete photos."""
    from backend.app.workers.pipeline import resume_incomplete_processing
    count = await resume_incomplete_processing()
    return {"status": "started", "queued": count}


@router.websocket("/ws")
async def pipeline_websocket(websocket: WebSocket):
    """WebSocket endpoint for real-time pipeline statistics."""
    await websocket.accept()

    try:
        while True:
            status = await get_pipeline_status()
            await websocket.send_json(status)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass