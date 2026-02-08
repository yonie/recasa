"""EXIF extraction service - reads metadata from photo files."""

import asyncio
import logging
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


def _dms_to_decimal(dms, ref: str) -> float | None:
    """Convert GPS DMS (degrees, minutes, seconds) to decimal degrees."""
    try:
        degrees = float(dms[0])
        minutes = float(dms[1])
        seconds = float(dms[2])
        decimal = degrees + minutes / 60 + seconds / 3600
        if ref in ("S", "W"):
            decimal = -decimal
        return decimal
    except (TypeError, ValueError, IndexError):
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
    """Extract EXIF metadata from an image file."""
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

            exif_data = img.getexif()
            if not exif_data:
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

            # GPS data
            gps_ifd = exif_data.get_ifd(0x8825)  # GPSInfo IFD
            if gps_ifd:
                gps_decoded = {}
                for tag_id, value in gps_ifd.items():
                    tag_name = GPSTAGS.get(tag_id, str(tag_id))
                    gps_decoded[tag_name] = value

                if "GPSLatitude" in gps_decoded and "GPSLatitudeRef" in gps_decoded:
                    result["gps_latitude"] = _dms_to_decimal(
                        gps_decoded["GPSLatitude"], gps_decoded["GPSLatitudeRef"]
                    )

                if "GPSLongitude" in gps_decoded and "GPSLongitudeRef" in gps_decoded:
                    result["gps_longitude"] = _dms_to_decimal(
                        gps_decoded["GPSLongitude"], gps_decoded["GPSLongitudeRef"]
                    )

                if "GPSAltitude" in gps_decoded:
                    alt = gps_decoded["GPSAltitude"]
                    if isinstance(alt, tuple):
                        result["gps_altitude"] = float(alt[0]) / float(alt[1]) if alt[1] else None
                    else:
                        result["gps_altitude"] = float(alt)

    except Exception:
        logger.exception("Error extracting EXIF from %s", filepath)

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
