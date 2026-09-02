"""EXIF extraction service - reads metadata from photo files."""

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path

from PIL import Image
from PIL.ExifTags import GPSTAGS, TAGS

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import settings
from backend.app.database import async_session
from backend.app.models import Photo
from backend.app.services.image_loader import is_raw

logger = logging.getLogger(__name__)


def _get_filesystem_date(filepath: Path) -> datetime | None:
    """Get the best available filesystem date for a file.

    Prefers the earlier of creation time and modification time,
    since the creation time is often when the file was copied
    and mtime can be the original date.
    """
    try:
        stat = filepath.stat()
        # st_mtime = last modification, st_ctime = creation on Windows / metadata change on Unix
        mtime = stat.st_mtime
        ctime = stat.st_ctime
        # Use the earlier timestamp (more likely to be the original date)
        best = min(mtime, ctime)
        return datetime.fromtimestamp(best)
    except OSError:
        return None


def _dms_to_decimal(dms, ref: str) -> float | None:
    """Convert GPS DMS (degrees, minutes, seconds) to decimal degrees.

    Accepts either PIL's tuple form ``(deg, min, sec)`` or the ratio form
    that exifread returns for RAW files: list of IfdTag objects whose
    ``.values`` are ``(numerator, denominator)`` Ratio pairs.
    """
    try:
        # PIL form: a plain tuple/list of three numbers
        if isinstance(dms, (tuple, list)) and len(dms) == 3 and all(
            isinstance(v, (int, float)) for v in dms
        ):
            degrees = float(dms[0])
            minutes = float(dms[1])
            seconds = float(dms[2])
        else:
            # exifread form: list of Ratio objects (numerator, denominator)
            parts = list(dms) if not isinstance(dms, (tuple, list)) else dms
            if len(parts) < 3:
                return None
            degrees = _ratio_to_float(parts[0])
            minutes = _ratio_to_float(parts[1])
            seconds = _ratio_to_float(parts[2])
        if degrees is None or minutes is None or seconds is None:
            return None
        # Reject only if all components are zero (invalid/placeholder GPS data)
        if degrees == 0 and minutes == 0 and seconds == 0:
            return None
        decimal = degrees + minutes / 60 + seconds / 3600
        if ref in ("S", "W"):
            decimal = -decimal
        return decimal
    except (TypeError, ValueError, IndexError, ZeroDivisionError):
        return None


def _ratio_to_float(value) -> float | None:
    """Convert an exifread Ratio / tuple / number to float."""
    try:
        if hasattr(value, "num") and hasattr(value, "den"):
            return float(value.num) / float(value.den) if value.den else None
        if isinstance(value, (tuple, list)) and len(value) == 2:
            num, den = value
            return float(num) / float(den) if den else None
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _parse_exif_datetime(value: str) -> datetime | None:
    """Parse EXIF datetime string."""
    formats = [
        "%Y:%m:%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y:%m:%d",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(value.strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None


def _apply_exif_dict(decoded: dict, result: dict, filepath: Path) -> None:
    """Populate `result` from a flat EXIF tag dict (PIL or exifread style).

    Keys are tag names like 'Make', 'GPSLatitude', etc. Values may be either
    PIL's native types (tuples for rationals) or exifread's IfdTag objects.
    """
    # Basic metadata
    if "Make" in decoded:
        result["camera_make"] = str(decoded["Make"]).strip()
    if "Model" in decoded:
        result["camera_model"] = str(decoded["Model"]).strip()
    if "LensModel" in decoded:
        result["lens_model"] = str(decoded["LensModel"]).strip()
    if "Orientation" in decoded:
        try:
            result["orientation"] = int(decoded["Orientation"])
        except (TypeError, ValueError):
            pass

    # Date taken
    for date_tag in ["DateTimeOriginal", "DateTimeDigitized", "DateTime"]:
        if date_tag in decoded:
            dt = _parse_exif_datetime(str(decoded[date_tag]))
            if dt:
                result["date_taken"] = dt
                result["date_source"] = "exif"
                break

    # Exposure info - tolerant of both PIL tuple form and exifread ratio form
    if "FocalLength" in decoded:
        result["focal_length"] = _ratio_to_float(decoded["FocalLength"])
    if "FNumber" in decoded:
        result["aperture"] = _ratio_to_float(decoded["FNumber"])
    if "ExposureTime" in decoded:
        et = decoded["ExposureTime"]
        et_val = _ratio_to_float(et)
        if et_val is not None:
            # Render as a fraction (e.g. "1/250") when both parts are known
            if hasattr(et, "num") and hasattr(et, "den") and et.den:
                result["shutter_speed"] = f"{int(et.num)}/{int(et.den)}"
            elif isinstance(et, (tuple, list)) and len(et) == 2 and et[1]:
                result["shutter_speed"] = f"{int(et[0])}/{int(et[1])}"
            else:
                result["shutter_speed"] = str(et_val)
    if "ISOSpeedRatings" in decoded:
        try:
            result["iso"] = int(decoded["ISOSpeedRatings"])
        except (TypeError, ValueError):
            pass

    # GPS data
    if "GPSLatitude" in decoded and "GPSLatitudeRef" in decoded:
        result["gps_latitude"] = _dms_to_decimal(
            decoded["GPSLatitude"], str(decoded["GPSLatitudeRef"])
        )
    if "GPSLongitude" in decoded and "GPSLongitudeRef" in decoded:
        result["gps_longitude"] = _dms_to_decimal(
            decoded["GPSLongitude"], str(decoded["GPSLongitudeRef"])
        )
    if "GPSAltitude" in decoded:
        result["gps_altitude"] = _ratio_to_float(decoded["GPSAltitude"])


def _extract_pil_exif(filepath: Path, result: dict) -> None:
    """Extract EXIF from formats PIL can open (JPEG/PNG/HEIC/TIFF/BMP)."""
    with Image.open(filepath) as img:
        result["width"] = img.width
        result["height"] = img.height

        exif_obj = img.getexif()
        if not exif_obj:
            return

        decoded = {}
        for tag_id, value in exif_obj.items():
            tag_name = TAGS.get(tag_id, str(tag_id))
            decoded[tag_name] = value

        # GPS lives in its own IFD - pull it out and merge with top-level dict
        try:
            gps_ifd = exif_obj.get_ifd(0x8825)  # GPSInfo IFD pointer
            if gps_ifd:
                for tag_id, value in gps_ifd.items():
                    gps_tag = GPSTAGS.get(tag_id, str(tag_id))
                    decoded[gps_tag] = value
        except (TypeError, ValueError, AttributeError):
            pass

        _apply_exif_dict(decoded, result, filepath)


def _extract_raw_exif(filepath: Path, result: dict) -> None:
    """Extract EXIF from RAW (ORF) files via exifread, and dimensions via rawpy."""
    from backend.app.services.image_loader import (
        get_raw_dimensions,
        extract_raw_exif_tags,
    )

    try:
        result["width"], result["height"] = get_raw_dimensions(filepath)
    except Exception as e:
        logger.debug("rawpy dimensions failed for %s: %s", filepath, type(e).__name__)

    decoded = extract_raw_exif_tags(filepath)
    if not decoded:
        return

    # exifread already returns flat tag names with prefixes stripped by our
    # helper, so we can feed directly to _apply_exif_dict.
    _apply_exif_dict(decoded, result, filepath)


def _extract_exif_data(filepath: Path) -> dict:
    """Extract EXIF metadata from an image file.

    Falls back to the file's filesystem modification time if no EXIF date is found,
    so that every photo gets a date_taken for timeline/event grouping.
    """
    result = {
        "width": None,
        "height": None,
        "date_taken": None,
        "date_source": None,
        "camera_make": None,
        "camera_model": None,
        "lens_model": None,
        "focal_length": None,
        "aperture": None,
        "shutter_speed": None,
        "iso": None,
        "orientation": None,
        "gps_latitude": None,
        "gps_longitude": None,
        "gps_altitude": None,
    }

    try:
        if is_raw(filepath):
            _extract_raw_exif(filepath, result)
        else:
            _extract_pil_exif(filepath, result)
    except Exception as e:
        logger.warning("Skipping EXIF for %s: %s", filepath, type(e).__name__)

    # Fallback: if no EXIF date was found, use filesystem date so the photo
    # still appears in timelines and can be grouped into events.
    if result["date_taken"] is None:
        result["date_taken"] = _get_filesystem_date(filepath)
        if result["date_taken"]:
            result["date_source"] = "filesystem"
            logger.debug("No EXIF date for %s, using filesystem date: %s", filepath, result["date_taken"])

    return result


async def extract_exif(file_hash: str) -> bool:
    """Extract EXIF data for a photo and update the database."""
    async with async_session() as session:
        photo = await session.get(Photo, file_hash)
        if not photo:
            logger.warning("Photo not found: %s", file_hash)
            return False

        # Check if EXIF already extracted (data exists)
        if photo.camera_make is not None or photo.date_taken is not None:
            return True

        filepath = settings.photos_dir / photo.file_path
        if not filepath.exists():
            logger.warning("File not found: %s", filepath)
            return False

        exif_data = await asyncio.to_thread(_extract_exif_data, filepath)

        # Update photo record
        for key, value in exif_data.items():
            if value is not None:
                setattr(photo, key, value)

        await session.commit()

        logger.debug("Extracted EXIF for %s", file_hash)
        return True
