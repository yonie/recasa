"""Pipeline status and statistics API endpoints."""

import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.app.workers.queues import pipeline, QueueType

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


@router.get("/status")
async def get_pipeline_status():
    """Get current pipeline status and statistics."""
    return pipeline.get_pipeline_stats()


@router.get("/queues")
async def get_queue_status():
    """Get status of all queues."""
    return {
        qtype.value: queue.get_stats()
        for qtype, queue in pipeline.queues.items()
    }


@router.get("/queues/{queue_type}")
async def get_specific_queue_status(queue_type: str):
    """Get status of a specific queue."""
    try:
        qtype = QueueType(queue_type)
        return pipeline.queues[qtype].get_stats()
    except ValueError:
        return {"error": f"Unknown queue type: {queue_type}"}


@router.get("/flow")
async def get_pipeline_flow():
    """Get the pipeline flow diagram."""
    return {
        "stages": [
            {
                "id": qt.value,
                "name": qt.value.replace("_", " ").title(),
                "next": [nq.value for nq in pipeline.get_next_queues(qt)],
            }
            for qt in QueueType
        ]
    }


@router.get("/debug")
async def get_debug_info():
    """Get detailed debug info about all queues."""
    debug_info = {
        "is_running": pipeline.is_running,
        "start_time": pipeline._start_time.isoformat() if pipeline._start_time else None,
        "total_discovered": pipeline._total_discovered,
        "queues": {},
    }
    for qtype, queue in pipeline.queues.items():
        debug_info["queues"][qtype.value] = {
            "pending": queue.stats.pending,
            "processing": queue.stats.processing,
            "completed_total": queue.stats.completed_total,
            "skipped_total": queue.stats.skipped_total,
            "failed_total": queue.stats.failed_total,
            "current_file_hash": queue.stats.current_file_hash,
            "current_file_path": queue.stats.current_file_path,
            "processed_count": len(queue._processed),
            "processing_set": list(queue._processing),
        }
    return debug_info


@router.post("/queue/{queue_type}/clear-processed")
async def clear_processed(queue_type: str):
    """Clear the processed set for a queue (for debugging/testing)."""
    try:
        qtype = QueueType(queue_type)
        queue = pipeline.queues[qtype]
        count = len(queue._processed)
        queue._processed.clear()
        return {"message": f"Cleared {count} processed items from {queue_type}"}
    except ValueError:
        return {"error": f"Unknown queue type: {queue_type}"}


@router.post("/queue/{queue_type}/add/{file_hash}")
async def add_to_queue(queue_type: str, file_hash: str, file_path: str = ""):
    """Manually add a file to a specific queue (for debugging)."""
    try:
        qtype = QueueType(queue_type)
        queue = pipeline.queues[qtype]
        success = await queue.put(file_hash)
        if success:
            queue.stats.current_file_path = file_path or file_hash
        return {"success": success, "queue": queue_type, "file_hash": file_hash}
    except ValueError:
        return {"error": f"Unknown queue type: {queue_type}"}


@router.post("/reset")
async def reset_pipeline():
    """Reset all queue processed sets (for debugging/testing)."""
    counts = {}
    for qtype, queue in pipeline.queues.items():
        counts[qtype.value] = len(queue._processed)
        queue._processed.clear()
    return {"message": "Reset all queues", "cleared_counts": counts}


@router.websocket("/ws")
async def pipeline_websocket(websocket: WebSocket):
    """WebSocket endpoint for real-time pipeline statistics."""
    await websocket.accept()

    try:
        while True:
            stats = pipeline.get_pipeline_stats()
            await websocket.send_json(stats)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
