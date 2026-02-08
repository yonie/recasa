"""Scan control and status API endpoints."""

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.app.schemas.photo import ScanStatus
from backend.app.workers.pipeline import run_initial_scan, scan_state

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
