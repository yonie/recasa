"""Thumbnail generation service."""

import asyncio
import logging
from pathlib import Path

from PIL import Image

from backend.app.config import settings
from backend.app.database import async_session
from backend.app.exceptions import PermanentStageError
from backend.app.models import Photo
from backend.app.services.image_loader import (
    HEIF_SUPPORTED,
    open_image_cm,
    PermanentReadError,
)

logger = logging.getLogger(__name__)


def _get_thumbnail_path(file_hash: str, size: int) -> Path:
    """Get the path for a thumbnail file, using hash prefix for directory sharding."""
    prefix = file_hash[:2]
    return settings.thumbnails_dir / prefix / f"{file_hash}_{size}.webp"


def _generate_thumbnail(
    filepath: Path, file_hash: str, sizes: list[int], is_video: bool = False
) -> list[Path]:
    """Generate thumbnails at multiple sizes for a photo. Returns list of created paths.

    For videos the poster is the first frame (extracted via ffmpeg); the rest
    of the resize pipeline is identical.
    """
    created = []

    try:
        if is_video:
            from backend.app.services.video import extract_poster_frame

            img = extract_poster_frame(filepath)
            if img is None:
                raise PermanentStageError("could not extract a video frame")
            _resize_and_save(img, file_hash, sizes, created)
            return created

        with open_image_cm(filepath) as img:
            # Handle EXIF orientation (PIL path only - rawpy bakes orientation in)
            try:
                from PIL import ImageOps
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass

            # Convert to RGB if needed (e.g., RGBA, palette)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            _resize_and_save(img, file_hash, sizes, created)

    except PermanentStageError:
        raise
    except PermanentReadError as e:
        raise PermanentStageError(str(e)) from e
    except Exception as e:
        logger.warning("Skipping corrupted image %s: %s", filepath, type(e).__name__)
        raise PermanentStageError(f"cannot read image ({type(e).__name__})") from e

    return created


def _resize_and_save(img, file_hash: str, sizes: list[int], created: list[Path]) -> None:
    """Write WebP thumbnails at each size from an already-open PIL image."""
    for size in sizes:
        thumb_path = _get_thumbnail_path(file_hash, size)
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        if thumb_path.exists():
            created.append(thumb_path)
            continue
        thumb = img.copy()
        thumb.thumbnail((size, size), Image.Resampling.LANCZOS)
        thumb.save(thumb_path, "WEBP", quality=80)
        created.append(thumb_path)


async def generate_thumbnails(file_hash: str) -> bool:
    """Generate thumbnails for a photo."""
    async with async_session() as session:
        photo = await session.get(Photo, file_hash)
        if not photo:
            logger.warning("Photo not found: %s", file_hash)
            return False

        # Check if thumbnails already exist
        thumb_path = _get_thumbnail_path(file_hash, 200)
        if thumb_path.exists():
            return True

        filepath = settings.photos_dir / photo.file_path
        if not filepath.exists():
            logger.warning("File not found: %s", filepath)
            return False

        created = await asyncio.to_thread(
            _generate_thumbnail, filepath, file_hash, settings.thumbnail_sizes, photo.is_video
        )

        if created:
            await session.commit()
            logger.debug("Generated %d thumbnails for %s", len(created), file_hash)
            return True

        return False


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
