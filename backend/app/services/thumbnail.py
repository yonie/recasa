"""Thumbnail generation service."""

import asyncio
import logging
from pathlib import Path

from PIL import Image

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import settings
from backend.app.database import async_session
from backend.app.models import Photo

logger = logging.getLogger(__name__)

# Try to register HEIF support
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIF_SUPPORTED = True
except ImportError:
    HEIF_SUPPORTED = False
    logger.warning("pillow-heif not available, HEIC files won't be supported")


def _get_thumbnail_path(file_hash: str, size: int) -> Path:
    """Get the path for a thumbnail file, using hash prefix for directory sharding."""
    prefix = file_hash[:2]
    return settings.thumbnails_dir / prefix / f"{file_hash}_{size}.webp"


def _generate_thumbnail(filepath: Path, file_hash: str, sizes: list[int]) -> list[Path]:
    """Generate thumbnails at multiple sizes for a photo. Returns list of created paths."""
    created = []

    try:
        with Image.open(filepath) as img:
            # Handle EXIF orientation
            try:
                from PIL import ImageOps
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass

            # Convert to RGB if needed (e.g., RGBA, palette)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            for size in sizes:
                thumb_path = _get_thumbnail_path(file_hash, size)
                thumb_path.parent.mkdir(parents=True, exist_ok=True)

                if thumb_path.exists():
                    created.append(thumb_path)
                    continue

                # Create thumbnail maintaining aspect ratio
                thumb = img.copy()
                thumb.thumbnail((size, size), Image.Resampling.LANCZOS)
                thumb.save(thumb_path, "WEBP", quality=80)
                created.append(thumb_path)

    except Exception:
        logger.exception("Error generating thumbnails for %s", filepath)

    return created


async def generate_thumbnails(file_hash: str) -> bool:
    """Generate thumbnails for a photo."""
    async with async_session() as session:
        photo = await session.get(Photo, file_hash)
        if not photo:
            logger.warning("Photo not found: %s", file_hash)
            return False

        if photo.thumbnail_generated:
            return True

        filepath = settings.photos_dir / photo.file_path
        if not filepath.exists():
            logger.warning("File not found: %s", filepath)
            return False

        created = await asyncio.to_thread(
            _generate_thumbnail, filepath, file_hash, settings.thumbnail_sizes
        )

        if created:
            photo.thumbnail_generated = True
            await session.commit()
            logger.debug("Generated %d thumbnails for %s", len(created), file_hash)
            return True

        return False


async def process_pending_thumbnails(batch_size: int | None = None) -> int:
    """Process all photos that haven't had thumbnails generated yet."""
    if batch_size is None:
        batch_size = settings.batch_size

    async with async_session() as session:
        result = await session.execute(
            select(Photo.file_hash)
            .where(Photo.thumbnail_generated == False)  # noqa: E712
            .limit(batch_size)
        )
        hashes = result.scalars().all()

    processed = 0
    for file_hash in hashes:
        if await generate_thumbnails(file_hash):
            processed += 1

    if processed:
        logger.info("Generated thumbnails for %d photos", processed)
    return processed


def get_thumbnail_path(file_hash: str, size: int = 600) -> Path | None:
    """Get the path to an existing thumbnail. Returns None if not found."""
    # Find the closest available size
    available_sizes = sorted(settings.thumbnail_sizes)
    best_size = available_sizes[0]
    for s in available_sizes:
        if s >= size:
            best_size = s
            break
    else:
        best_size = available_sizes[-1]

    thumb_path = _get_thumbnail_path(file_hash, best_size)
    if thumb_path.exists():
        return thumb_path
    return None
