"""Print export service: stream marked photos as a flat zip.

Print services generally don't accept HEIC, so those are converted to JPEG
on the fly; all other files are passed through untouched. Filenames get a
date prefix so they sort chronologically in upload forms.
"""

import io
import logging
import zipfile
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

HEIC_SUFFIXES = {".heic", ".heif"}
HEIC_MIME_TYPES = {"image/heic", "image/heif"}

# RAW formats - print services don't accept these, convert to JPEG.
RAW_SUFFIXES = {".orf"}

# Photos are already compressed — ZIP_STORED avoids pointless recompression.
_ZIP_MODE = zipfile.ZIP_STORED


class _StreamBuffer:
    """Minimal file-like object that lets us drain zip output incrementally."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._offset = 0

    def write(self, data: bytes) -> int:
        self._buf += data
        return len(data)

    def flush(self) -> None:
        pass

    def tell(self) -> int:
        return self._offset + len(self._buf)

    def drain(self) -> bytes:
        data = bytes(self._buf)
        self._offset += len(self._buf)
        self._buf.clear()
        return data


def _is_heic(filepath: Path, mime_type: str | None) -> bool:
    return filepath.suffix.lower() in HEIC_SUFFIXES or (mime_type or "") in HEIC_MIME_TYPES


def _is_raw(filepath: Path) -> bool:
    return filepath.suffix.lower() in RAW_SUFFIXES


def _convert_heic_to_jpeg(filepath: Path) -> bytes | None:
    """Convert a HEIC file to JPEG bytes, baking in EXIF orientation."""
    try:
        from PIL import Image, ImageOps

        # Registers the HEIF opener as an import side effect (logs if missing).
        from backend.app.services.thumbnail import HEIF_SUPPORTED

        if not HEIF_SUPPORTED:
            return None

        with Image.open(filepath) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            out = io.BytesIO()
            img.save(out, "JPEG", quality=95)
            return out.getvalue()
    except Exception as e:  # noqa: BLE001 - a file that will not convert ships as is
        logger.warning("HEIC conversion failed for %s: %s", filepath, type(e).__name__)
        return None


def _convert_raw_to_jpeg(filepath: Path) -> bytes | None:
    """Convert a RAW (ORF) file to JPEG bytes via rawpy."""
    try:
        from backend.app.services.image_loader import open_image_cm

        with open_image_cm(filepath) as img:
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            out = io.BytesIO()
            img.save(out, "JPEG", quality=95)
            return out.getvalue()
    except Exception as e:  # noqa: BLE001 - a file that will not convert ships as is
        logger.warning("RAW conversion failed for %s: %s", filepath, type(e).__name__)
        return None


def _zip_name(file_name: str, date_taken: datetime | None, used: set[str]) -> str:
    """Date-prefixed, collision-free name for a file inside the zip."""
    name = f"{date_taken:%Y-%m-%d}_{file_name}" if date_taken else file_name
    if name in used:
        stem, dot, ext = name.rpartition(".")
        base = stem if dot else name
        suffix = ext if dot else ""
        counter = 2
        while name in used:
            name = f"{base}_{counter}.{suffix}" if suffix else f"{base}_{counter}"
            counter += 1
    used.add(name)
    return name


def build_print_zip(
    entries: list[tuple[Path, str, str | None, datetime | None]],
) -> Iterator[bytes]:
    """Yield zip bytes for (filepath, file_name, mime_type, date_taken) entries.

    Runs as a sync generator (FastAPI iterates it in a threadpool), holding at
    most one file in memory at a time.
    """
    buffer = _StreamBuffer()
    used_names: set[str] = set()

    with zipfile.ZipFile(buffer, "w", _ZIP_MODE) as zf:
        for filepath, file_name, mime_type, date_taken in entries:
            if not filepath.exists():
                logger.warning("Skipping missing file in print export: %s", filepath)
                continue

            data: bytes | None = None
            out_name = file_name
            if _is_heic(filepath, mime_type):
                data = _convert_heic_to_jpeg(filepath)
                if data is not None:
                    out_name = f"{filepath.stem}.jpg"
            elif _is_raw(filepath):
                data = _convert_raw_to_jpeg(filepath)
                if data is not None:
                    out_name = f"{filepath.stem}.jpg"
            if data is None:
                data = filepath.read_bytes()

            zf.writestr(_zip_name(out_name, date_taken, used_names), data)
            chunk = buffer.drain()
            if chunk:
                yield chunk

    # Central directory written on ZipFile close.
    chunk = buffer.drain()
    if chunk:
        yield chunk
