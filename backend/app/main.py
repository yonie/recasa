"""Recasa - Intelligent Local Photo Explorer."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.app.api import (
    config,
    directories,
    duplicates,
    events,
    locations,
    persons,
    photos,
    pipeline_api,
    scan,
    tags,
    timeline,
    user_data,
)
from backend.app.api.guards import CrossSiteGuardMiddleware
from backend.app.api.limits import BodySizeLimitMiddleware
from backend.app.config import settings
from backend.app.database import init_db
from backend.app.workers.pipeline import resume_incomplete_processing, start_file_watcher
from backend.app.workers.queues import pipeline
from backend.app.workers.worker import start_pipeline_workers

logger = logging.getLogger("recasa")

VERSION = "1.7.0"


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
    await config.init_config_store()

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
        rescan_task = asyncio.create_task(scan.periodic_rescan_loop(settings.watch_interval))
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
    version=VERSION,
    lifespan=lifespan,
)

# No CORS middleware, on purpose. The UI is same-origin (nginx serves it and
# proxies /api), and the Vite dev server proxies /api too, so no browser ever
# needs a cross-origin grant. The wildcard-with-credentials policy this app
# used to send let any website the owner visited read the whole photo API
# with the browser's cached nginx basic-auth credentials. The guard below
# closes the other direction: other sites making the browser write to it.

app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(CrossSiteGuardMiddleware)

for module in (
    photos,
    directories,
    timeline,
    scan,
    duplicates,
    persons,
    events,
    locations,
    pipeline_api,
    tags,
    config,
    user_data,
):
    app.include_router(module.router)


@app.exception_handler(OverflowError)
async def _number_out_of_range(request: Request, exc: OverflowError) -> JSONResponse:
    # An integer parameter too large for SQLite (a page, id or year past
    # 2**63) used to surface as a bare 500 from the database driver.
    return JSONResponse(status_code=422, content={"detail": "Number out of range"})


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "app": "recasa", "version": VERSION}
