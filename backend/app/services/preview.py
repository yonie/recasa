"""Full-view previews for formats browsers can't decode.

The photo viewer shows the original file directly, which works for JPEG/PNG/
WebP but not for RAW (ORF) — no browser has a LibRaw decoder — nor for HEIC
outside Safari. For those the <img> simply fails to load, so we render a JPEG
once and cache it on disk, keyed by file hash.

This is deliberately separate from the thumbnail pipeline: thumbnails are
generated for every photo at ingest time, whereas previews are only ever needed
for the files a user actually opens in the viewer.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from PIL import Image, ImageOps

from backend.app.config import settings
from backend.app.services.image_loader import is_raw, open_image_cm

logger = logging.getLogger(__name__)


# HEIC decodes in Safari but nowhere else, so it needs the same treatment as
# RAW to be viewable in Chrome and Firefox.
_NON_WEB_SUFFIXES = {".heic", ".heif"}


def needs_preview(filepath: Path) -> bool:
    """True if the browser can't render this file and a preview is required."""
    return is_raw(filepath) or filepath.suffix.lower() in _NON_WEB_SUFFIXES


def preview_path(file_hash: str) -> Path:
    """Cache location for a rendered preview (hash-prefix sharded, as thumbs)."""
    return settings.previews_dir / file_hash[:2] / f"{file_hash}.jpg"


def render_preview(filepath: Path, file_hash: str) -> Path:
    """Render and cache a web-viewable JPEG preview. Returns the cached path.

    Runs the RAW decode, so call this in a thread. Idempotent: an existing
    cache entry is returned untouched.
    """
    out = preview_path(file_hash)
    if out.exists():
        return out

    out.parent.mkdir(parents=True, exist_ok=True)
    with open_image_cm(filepath) as img:
        # rawpy bakes orientation in; this is a no-op for RAW and correct for
        # any non-RAW format that later needs a preview.
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:  # noqa: BLE001, S110 - a broken EXIF block just means no rotation
            pass
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        limit = settings.preview_max_dimension
        if limit and max(img.size) > limit:
            img.thumbnail((limit, limit), Image.Resampling.LANCZOS)

        # Write to a temp file first so a concurrent request never reads a
        # half-written JPEG.
        tmp = out.with_suffix(".jpg.part")
        img.save(tmp, "JPEG", quality=90, optimize=True)
        tmp.replace(out)

    logger.debug("Rendered preview for %s", filepath.name)
    return out


_gate: asyncio.Semaphore | None = None


def render_gate() -> asyncio.Semaphore:
    """Bounds concurrent cold-path preview work.

    Built lazily so it binds to the running loop rather than to import time.

    Callers should hold this across the whole cold path, database read
    included: a request queued behind a decode must not be sitting on a pooled
    connection, or a burst of them starves every other endpoint
    (``list_photos``, ``get_stats``) until those time out.
    """
    global _gate
    if _gate is None:
        _gate = asyncio.Semaphore(settings.preview_concurrency)
    return _gate
