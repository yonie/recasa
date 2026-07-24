"""Recasa - Intelligent Local Photo Explorer."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config import settings
from backend.app.database import init_db
from backend.app.api import photos, directories, timeline, scan, duplicates, persons, events, locations, pipeline_api, tags, config, user_data
from backend.app.workers.queues import pipeline
from backend.app.workers.worker import start_pipeline_workers
from backend.app.workers.pipeline import start_file_watcher, resume_incomplete_processing

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

    # Initialize config store (stores photos_path for change detection)
    from backend.app.api.config import init_config_store
    await init_config_store()

    # Start the pipeline workers (face detection, event detection, etc.)
    workers = await start_pipeline_workers(pipeline)

    # Resume processing for photos that were interrupted
    await resume_incomplete_processing()

    # Start file watcher for live-detecting new photos. inotify events don't
    # cross Docker bind mounts on Windows/macOS hosts, so a periodic rescan
    # sweep (WATCH_INTERVAL) backs it up; the scanner's size+mtime check keeps
    # empty sweeps cheap.
    observer = await start_file_watcher()

    rescan_task = None
    if settings.watch_interval > 0:
        import asyncio
        from backend.app.api.scan import periodic_rescan_loop
        rescan_task = asyncio.create_task(periodic_rescan_loop(settings.watch_interval))
    else:
        logger.info("Periodic rescan disabled (WATCH_INTERVAL=0)")

    yield

    # Shutdown
    logger.info("Shutting down Recasa")
    if rescan_task:
        rescan_task.cancel()
    for worker in workers:
        worker.stop()
    if observer:
        observer.stop()
        observer.join(timeout=5)


app = FastAPI(
    title="Recasa",
    description="Intelligent Local Photo Explorer",
    version="1.7.0",
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
app.include_router(events.router)
app.include_router(locations.router)
app.include_router(pipeline_api.router)
app.include_router(tags.router)
app.include_router(config.router)
app.include_router(user_data.router)


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "app": "recasa", "version": "1.7.0"}
