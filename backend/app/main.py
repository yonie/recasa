"""Recasa - Intelligent Local Photo Explorer."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config import settings
from backend.app.database import init_db
from backend.app.api import photos, directories, timeline, scan, duplicates, persons, tags, events, locations
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

    # Start initial scan in background
    scan_task = asyncio.create_task(run_initial_scan())

    # Start file watcher
    observer = await start_file_watcher()

    yield

    # Shutdown
    logger.info("Shutting down Recasa")
    if observer:
        observer.stop()
        observer.join(timeout=5)
    scan_task.cancel()


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


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "app": "recasa", "version": "0.2.0"}
