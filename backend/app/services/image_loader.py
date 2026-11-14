"""Central image loader: route RAW formats (ORF) through rawpy.

PIL cannot decode ORF (Olympus RAW) files. rawpy wraps LibRaw and returns a
numpy array; we wrap it back into a PIL Image so the rest of the pipeline is
format-agnostic. HEIF registration is also centralized here.

Per-stage code calls ``open_image_cm(filepath)`` (context manager with cleanup)
instead of ``Image.open(filepath)``. For the non-RAW path this just wraps
``Image.open``; for the RAW path it decodes via rawpy and returns a PIL Image.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from PIL import Image

from backend.app.config import settings

logger = logging.getLogger(__name__)

# Register HEIF support as an import side effect (HEIC/HEIF via pillow-heif).
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIF_SUPPORTED = True
except ImportError:
    HEIF_SUPPORTED = False
    logger.warning("pillow-heif not available, HEIC files won't be supported")

# rawpy is optional at import time but required to actually read ORF files.
try:
    import rawpy

    RAWPY_SUPPORTED = True
except ImportError:
    rawpy = None  # type: ignore[assignment]
    RAWPY_SUPPORTED = False
    logger.warning("rawpy not available, ORF files won't be supported")


def is_raw(filepath: Path) -> bool:
    """True if this file is a RAW format that PIL can't decode natively."""
    return filepath.suffix.lower() in settings.raw_extensions


def open_image(filepath: Path) -> Image.Image:
    """Open ANY supported image (JPEG/PNG/HEIC/TIFF/BMP/ORF) as a PIL Image.

    Caller is responsible for closing the image (``.close()``) when done, or
    use ``open_image_cm`` for a context manager that handles cleanup uniformly.
    """
    if is_raw(filepath):
        if not RAWPY_SUPPORTED:
            raise PermanentReadError("rawpy not installed, cannot read RAW file")
        return _open_raw(filepath)
    return Image.open(filepath)


@contextmanager
def open_image_cm(filepath: Path) -> Iterator[Image.Image]:
    """Context-manager wrapper around open_image with guaranteed cleanup."""
    img = open_image(filepath)
    try:
        yield img
    finally:
        try:
            img.close()
        except Exception:
            pass


class PermanentReadError(Exception):
    """Raised when an image cannot be read due to a permanent condition
    (missing decoder). The worker maps this to a PermanentStageError."""


def _open_raw(filepath: Path) -> Image.Image:
    """Decode a RAW file (ORF) via rawpy into an RGB PIL Image.

    rawpy.postprocess returns a numpy array (uint8, RGB). We convert to PIL.
    EXIF orientation is applied via the camera matrix during postprocessing
    (``output_color=rawpy.ColorSpace.sRGB``, auto-brightening off for fidelity).
    """
    import numpy as np

    assert rawpy is not None  # guaranteed by RAWPY_SUPPORTED check
    with rawpy.imread(str(filepath)) as raw:
        rgb = raw.postprocess(
            output_bps=8,  # 8-bit per channel
            output_color=rawpy.ColorSpace.sRGB,
            use_camera_wb=True,
            no_auto_bright=False,  # use auto brightness for preview-quality output
            gamma=(2.222, 4.5),
        )
    return Image.fromarray(np.asarray(rgb), mode="RGB")


def get_raw_dimensions(filepath: Path) -> tuple[int, int]:
    """Get (width, height) of a RAW file without full decode (fast path)."""
    assert rawpy is not None
    with rawpy.imread(str(filepath)) as raw:
        sizes = raw.sizes
        return sizes.width, sizes.height


def extract_raw_exif_tags(filepath: Path) -> dict:
    """Read EXIF tags from a RAW (ORF) file using exifread.

    exifread parses the embedded EXIF block directly from the file bytes, so
    it works on formats PIL can't open. Returns a flat dict of tag name -> value
    mirroring the keys exif.py expects from PIL's ``getexif()`` decoded dict:
    ``Make``, ``Model``, ``LensModel``, ``Orientation``, ``DateTimeOriginal``,
    ``DateTimeDigitized``, ``DateTime``, ``FocalLength``, ``FNumber``,
    ``ExposureTime``, ``ISOSpeedRatings``, plus GPS keys (``GPSLatitude``,
    ``GPSLatitudeRef``, etc.). Returns ``{}`` on any error.
    """
    import exifread

    try:
        with open(filepath, "rb") as f:
            tags = exifread.process_file(f, details=False)
    except Exception as e:
        logger.debug("exifread failed on %s: %s", filepath, type(e).__name__)
        return {}

    # exifread returns tag names like "Image Make", "EXIF DateTimeOriginal",
    # "GPS GPSLatitude". Strip the namespace prefix so keys match PIL's TAGS.
    flat: dict[str, object] = {}
    for name, tag in tags.items():
        # Skip non-metadata entries exifread injects
        if name in {"JPEGThumbnail", "TIFFThumbnail", "Filename", "EXIF MakerNote"}:
            continue
        parts = name.split(" ", 1)
        key = parts[-1] if len(parts) == 2 else name
        # Normalize common tags that PIL keys differently
        if key in {"ISO", "ISOSpeedRatings"}:
            key = "ISOSpeedRatings"
        values = tag.values if hasattr(tag, "values") else tag
        # Scalar tags (FocalLength, FNumber, ExposureTime, ISOSpeedRatings,
        # Orientation) come as a single-element list; unwrap them so consumers
        # get the value directly. DMS GPS tags legitimately have 3 elements
        # and stay as lists.
        if isinstance(values, list) and len(values) == 1 and key not in {
            "GPSLatitude", "GPSLongitude", "GPSAltitude"
        }:
            values = values[0]
        flat[key] = values
    return flat