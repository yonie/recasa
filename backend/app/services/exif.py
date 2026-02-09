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
    """Convert GPS DMS (degrees, minutes, seconds) to decimal degrees."""
    try:
        if not dms or len(dms) < 3:
            return None
        degrees = float(dms[0])
        minutes = float(dms[1])
        seconds = float(dms[2])
        # Reject only if all components are zero (invalid/placeholder GPS data)
        if degrees == 0 and minutes == 0 and seconds == 0:
            return None
        decimal = degrees + minutes / 60 + seconds / 3600
        if ref in ("S", "W"):
            decimal = -decimal
        return decimal
    except (TypeError, ValueError, IndexError, ZeroDivisionError):
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


def _extract_exif_data(filepath: Path) -> dict:
    """Extract EXIF metadata from an image file.

    Falls back to the file's filesystem modification time if no EXIF date is found,
    so that every photo gets a date_taken for timeline/event grouping.
    """
    result = {
        "width": None,
        "height": None,
        "date_taken": None,
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
        with Image.open(filepath) as img:
            result["width"] = img.width
            result["height"] = img.height

            # Use _getexif() for full EXIF data (getexif() is incomplete)
            exif_data = img._getexif()
            if not exif_data:
                # No EXIF at all -- fall back to filesystem date
                result["date_taken"] = _get_filesystem_date(filepath)
                return result

            # Decode EXIF tags
            decoded = {}
            for tag_id, value in exif_data.items():
                tag_name = TAGS.get(tag_id, str(tag_id))
                decoded[tag_name] = value

            # Basic metadata
            if "Make" in decoded:
                result["camera_make"] = str(decoded["Make"]).strip()
            if "Model" in decoded:
                result["camera_model"] = str(decoded["Model"]).strip()
            if "LensModel" in decoded:
                result["lens_model"] = str(decoded["LensModel"]).strip()
            if "Orientation" in decoded:
                result["orientation"] = int(decoded["Orientation"])

            # Date taken
            for date_tag in ["DateTimeOriginal", "DateTimeDigitized", "DateTime"]:
                if date_tag in decoded:
                    dt = _parse_exif_datetime(str(decoded[date_tag]))
                    if dt:
                        result["date_taken"] = dt
                        break

            # Exposure info
            if "FocalLength" in decoded:
                fl = decoded["FocalLength"]
                if isinstance(fl, tuple):
                    result["focal_length"] = float(fl[0]) / float(fl[1]) if fl[1] else None
                else:
                    result["focal_length"] = float(fl)

            if "FNumber" in decoded:
                fn = decoded["FNumber"]
                if isinstance(fn, tuple):
                    result["aperture"] = float(fn[0]) / float(fn[1]) if fn[1] else None
                else:
                    result["aperture"] = float(fn)

            if "ExposureTime" in decoded:
                et = decoded["ExposureTime"]
                if isinstance(et, tuple):
                    if et[1] and et[0]:
                        result["shutter_speed"] = f"{et[0]}/{et[1]}"
                else:
                    result["shutter_speed"] = str(et)

            if "ISOSpeedRatings" in decoded:
                result["iso"] = int(decoded["ISOSpeedRatings"])

            # GPS data - _getexif() nests GPS tags inside the GPSInfo tag (34853)
            try:
                gps_info = exif_data.get(34853)  # GPSInfo tag
                if gps_info and isinstance(gps_info, dict):
                    gps_latitude = gps_info.get(2)  # GPSLatitude
                    gps_latitude_ref = gps_info.get(1)  # GPSLatitudeRef
                    gps_longitude = gps_info.get(4)  # GPSLongitude
                    gps_longitude_ref = gps_info.get(3)  # GPSLongitudeRef
                    gps_altitude = gps_info.get(6)  # GPSAltitude

                    if gps_latitude and gps_latitude_ref:
                        result["gps_latitude"] = _dms_to_decimal(gps_latitude, gps_latitude_ref)

                    if gps_longitude and gps_longitude_ref:
                        result["gps_longitude"] = _dms_to_decimal(gps_longitude, gps_longitude_ref)

                    if gps_altitude is not None:
                        if isinstance(gps_altitude, tuple):
                            result["gps_altitude"] = float(gps_altitude[0]) / float(gps_altitude[1]) if gps_altitude[1] else None
                        else:
                            result["gps_altitude"] = float(gps_altitude)
            except (TypeError, ValueError):
                pass

    except Exception:
        logger.exception("Error extracting EXIF from %s", filepath)

    # Fallback: if no EXIF date was found, use filesystem date so the photo
    # still appears in timelines and can be grouped into events.
    if result["date_taken"] is None:
        result["date_taken"] = _get_filesystem_date(filepath)
        if result["date_taken"]:
            logger.debug("No EXIF date for %s, using filesystem date: %s", filepath, result["date_taken"])

    return result


async def extract_exif(file_hash: str) -> bool:
    """Extract EXIF data for a photo and update the database."""
    async with async_session() as session:
        photo = await session.get(Photo, file_hash)
        if not photo:
            logger.warning("Photo not found: %s", file_hash)
            return False

        if photo.exif_extracted:
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

        photo.exif_extracted = True
        await session.commit()

        logger.debug("Extracted EXIF for %s", file_hash)
        return True


async def process_pending_exif(batch_size: int | None = None) -> int:
    """Process all photos that haven't had EXIF extracted yet."""
    if batch_size is None:
        batch_size = settings.batch_size

    async with async_session() as session:
        result = await session.execute(
            select(Photo.file_hash).where(Photo.exif_extracted == False).limit(batch_size)  # noqa: E712
        )
        hashes = result.scalars().all()

    processed = 0
    for file_hash in hashes:
        if await extract_exif(file_hash):
            processed += 1

    if processed:
        logger.info("Extracted EXIF for %d photos", processed)
    return processed
