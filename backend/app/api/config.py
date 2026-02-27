"""Configuration status API endpoints.

Provides endpoints for checking app configuration and detecting changes
that may require user action (e.g., photos path changed).
"""

import logging

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import settings
from backend.app.database import async_session
from backend.app.models import ConfigStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/config", tags=["config"])

PHOTOS_PATH_KEY = "photos_path"


async def get_stored_photos_path() -> str | None:
    """Get the stored photos path from the database."""
    async with async_session() as session:
        result = await session.execute(
            select(ConfigStore).where(ConfigStore.key == PHOTOS_PATH_KEY)
        )
        config = result.scalar_one_or_none()
        if config:
            return config.value
        return None


async def store_photos_path(path: str) -> None:
    """Store the current photos path in the database."""
    async with async_session() as session:
        existing = await session.get(ConfigStore, PHOTOS_PATH_KEY)
        if existing:
            existing.value = path
        else:
            session.add(ConfigStore(key=PHOTOS_PATH_KEY, value=path))
        await session.commit()


async def init_config_store() -> None:
    """Initialize config store with current values if not present."""
    current_path = str(settings.photos_dir)
    stored_path = await get_stored_photos_path()
    
    if stored_path is None:
        await store_photos_path(current_path)
        logger.info("Initialized config store with photos_path: %s", current_path)


@router.get("/status")
async def get_config_status():
    """Get configuration status including path change detection.
    
    Returns:
        - current_photos_path: The currently configured photos directory
        - stored_photos_path: The photos directory stored in the database
        - path_changed: Whether the path has changed since last run
        - suggestion: User-facing message if action is needed
    """
    current_path = str(settings.photos_dir)
    stored_path = await get_stored_photos_path()
    
    if stored_path is None:
        await store_photos_path(current_path)
        stored_path = current_path
    
    path_changed = stored_path != current_path
    
    suggestion = None
    if path_changed:
        suggestion = (
            f"Your photos path has changed from '{stored_path}' to '{current_path}'. "
            "The index may reference files that are no longer accessible. "
            "Consider clearing the index and rescanning."
        )
    
    return {
        "current_photos_path": current_path,
        "stored_photos_path": stored_path,
        "path_changed": path_changed,
        "suggestion": suggestion,
        "enabled_stages": {
            "exif": True,
            "geocoding": settings.ENABLE_GEOCODING,
            "thumbnails": True,
            "motion_photos": True,
            "hashing": True,
            "faces": settings.ENABLE_FACE_DETECTION,
            "captioning": settings.ENABLE_CAPTIONING,
        },
        "ollama_url": settings.ollama_url,
        "ollama_model": settings.ollama_model,
    }


@router.post("/acknowledge-path-change")
async def acknowledge_path_change():
    """Acknowledge the path change and update stored path.
    
    This updates the stored photos path to the current one,
    dismissing the warning until the path changes again.
    """
    current_path = str(settings.photos_dir)
    await store_photos_path(current_path)
    logger.info("Acknowledged path change, stored: %s", current_path)
    
    return {
        "status": "acknowledged",
        "stored_photos_path": current_path,
    }