"""Recasa - Intelligent Local Photo Explorer."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config import settings
from backend.app.database import init_db
from backend.app.api import photos, directories, timeline, scan, duplicates, persons, tags, events, locations, pipeline
from backend.app.workers.queues import pipeline as pipeline_instance
from backend.app.workers.worker import start_pipeline_workers
from backend.app.workers.pipeline import run_initial_scan, start_file_watcher

logger = logging.getLogger("recasa")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown."""
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    logger.info("Starting Recasa - Intelligent Local Photo Explorer")
    logger.info("Photos directory: %s", settings.photos_dir)
    logger.info("Data directory: %s", settings.data_dir)

    # Ensure directories exist
    settings.thumbnails_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "db").mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "faces").mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "motion_videos").mkdir(parents=True, exist_ok=True)

    # Initialize database
    await init_db()

    # Start the pipeline workers (face detection, CLIP tagging, event detection, etc.)
    workers = await start_pipeline_workers(pipeline_instance)

    # Start initial scan in background -- feeds discovered files to pipeline
    async def _initial_scan():
        try:
            stats = await run_initial_scan()
            logger.info(
                "Initial scan complete: %d total, %d new, %d updated",
                stats.get("total", 0),
                stats.get("new", 0),
                stats.get("updated", 0),
            )
        except Exception:
            logger.exception("Initial scan failed")

    scan_task = asyncio.create_task(_initial_scan())

    # Start file watcher for live-detecting new photos
    observer = await start_file_watcher()

    yield

    # Shutdown
    logger.info("Shutting down Recasa")
    scan_task.cancel()
    for worker in workers:
        worker.stop()
    if observer:
        observer.stop()
        observer.join(timeout=5)


app = FastAPI(
    title="Recasa",
    description="Intelligent Local Photo Explorer",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS middleware for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(photos.router)
app.include_router(directories.router)
app.include_router(timeline.router)
app.include_router(scan.router)
app.include_router(duplicates.router)
app.include_router(persons.router)
app.include_router(tags.router)
app.include_router(events.router)
app.include_router(locations.router)
app.include_router(pipeline.router)


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "app": "recasa", "version": "0.2.0"}
