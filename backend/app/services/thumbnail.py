"""Thumbnail generation service.

Thumbnails live at ``thumbs/{hash[:2]}/{hash}_{size}.webp``. The 200px file is
the stage's "done" marker (see ``thumb_exists``), so it is always written last
and every file is written atomically: a crash can leave the larger sizes
missing, but never a truncated file that looks finished.
"""

import logging
import os
import threading
from pathlib import Path

from PIL import Image, ImageOps

from backend.app.config import settings
from backend.app.database import async_session
from backend.app.exceptions import PermanentStageError
from backend.app.models import Photo
from backend.app.services.image_loader import (
    HEIF_SUPPORTED,  # noqa: F401  (re-exported: print_export reads it from here)
    PermanentReadError,
    is_raw,
    open_image_cm,
)
from backend.app.services.media_task import run_media_task

logger = logging.getLogger(__name__)

# The size whose file marks the thumbnail stage as done.
MARKER_SIZE = 200
_MARKER_SUFFIX = f"_{MARKER_SIZE}.webp"


def _get_thumbnail_path(file_hash: str, size: int) -> Path:
    """Get the path for a thumbnail file, using hash prefix for directory sharding."""
    prefix = file_hash[:2]
    return settings.thumbnails_dir / prefix / f"{file_hash}_{size}.webp"


def thumb_exists(file_hash: str) -> bool:
    """True when the thumbnail stage's output exists for this photo."""
    return _get_thumbnail_path(file_hash, MARKER_SIZE).exists()


def existing_thumb_hashes() -> set[str]:
    """Every file_hash for which ``thumb_exists`` is true, from directory listings.

    Reading the 256 shard directories is far cheaper than one stat per photo,
    which matters at startup and on full rescans of a 40k library. Blocking:
    call it from a worker thread.
    """
    found: set[str] = set()
    try:
        shards = list(os.scandir(settings.thumbnails_dir))
    except OSError:
        return found
    for shard in shards:
        if not shard.is_dir():
            continue
        try:
            with os.scandir(shard.path) as entries:
                for entry in entries:
                    name = entry.name
                    # Same file thumb_exists would look for: right shard, 200px.
                    if name.endswith(_MARKER_SUFFIX) and name.startswith(shard.name):
                        found.add(name[: -len(_MARKER_SUFFIX)])
        except OSError:
            continue
    return found


def _save_atomic(img: Image.Image, path: Path) -> None:
    """Write a WebP via a temp file and rename, so readers never see a partial file.

    The temp name is unique per thread: the API's on-demand path and the
    pipeline worker can render the same photo at the same time.
    """
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        img.save(tmp, "WEBP", quality=80)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _resize_and_save(img: Image.Image, file_hash: str, sizes: list[int]) -> list[Path]:
    """Write WebP thumbnails at each size from an already-open, upright image.

    Sizes are rendered largest first, each from the previous one, so the full
    image is only resampled once and the marker size is written last.
    Existing files are kept as they are. Shrinks `img` in place: callers pass
    an image they own and do not reuse.
    """
    created: list[Path] = []
    for size in sorted(sizes, reverse=True):
        img.thumbnail((size, size), Image.Resampling.LANCZOS)
        thumb_path = _get_thumbnail_path(file_hash, size)
        if not thumb_path.exists():
            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            _save_atomic(img, thumb_path)
        created.append(thumb_path)
    return created


def _generate_thumbnail(
    filepath: Path, file_hash: str, sizes: list[int], is_video: bool = False
) -> list[Path]:
    """Generate thumbnails at multiple sizes for a photo. Returns list of paths.

    For videos the poster is the first frame (extracted via ffmpeg); the rest
    of the resize pipeline is identical.
    """
    try:
        if is_video:
            from backend.app.services.video import extract_poster_frame

            img = extract_poster_frame(filepath)
            if img is None:
                raise PermanentStageError("could not extract a video frame")
            return _resize_and_save(img, file_hash, sizes)

        with open_image_cm(filepath) as img:
            if not is_raw(filepath):
                # Let JPEG decode at a reduced scale that still covers the
                # largest thumbnail: several times faster and a fraction of the
                # memory on a 24 MP photo. A no-op for other formats.
                largest = max(sizes)
                img.draft(None, (largest, largest))

            # Handle EXIF orientation (PIL path only - rawpy bakes orientation in)
            try:
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass

            # Convert to RGB if needed (e.g., RGBA, palette)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            return _resize_and_save(img, file_hash, sizes)

    except PermanentStageError:
        raise
    except PermanentReadError as e:
        raise PermanentStageError(str(e)) from e
    except Exception as e:
        logger.warning("Skipping corrupted image %s: %s", filepath, type(e).__name__)
        raise PermanentStageError(f"cannot read image ({type(e).__name__})") from e


async def generate_thumbnails(file_hash: str) -> bool:
    """Generate thumbnails for a photo."""
    async with async_session() as session:
        photo = await session.get(Photo, file_hash)
        if not photo:
            logger.warning("Photo not found: %s", file_hash)
            return False
        file_path, is_video = photo.file_path, photo.is_video

    if thumb_exists(file_hash):
        return True

    filepath = settings.photos_dir / file_path
    if not filepath.exists():
        logger.warning("File not found: %s", filepath)
        return False

    created = await run_media_task(
        _generate_thumbnail, filepath, file_hash, settings.thumbnail_sizes, is_video
    )
    if created:
        logger.debug("Generated %d thumbnails for %s", len(created), file_hash)
        return True
    return False


def get_thumbnail_path(file_hash: str, size: int = 600) -> Path | None:
    """Get the path to an existing thumbnail. Returns None if not found."""
    # The smallest generated size that covers the request, else the largest.
    available_sizes = sorted(settings.thumbnail_sizes)
    best_size = next((s for s in available_sizes if s >= size), available_sizes[-1])

    thumb_path = _get_thumbnail_path(file_hash, best_size)
    if thumb_path.exists():
        return thumb_path
    return None
