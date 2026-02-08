"""Reverse geocoding service - converts GPS coordinates to location names."""

import logging

from sqlalchemy import select

from backend.app.config import settings
from backend.app.database import async_session
from backend.app.models import Photo

logger = logging.getLogger(__name__)

# Lazy-loaded reverse geocoder
_geocoder = None


def _get_geocoder():
    global _geocoder
    if _geocoder is None:
        try:
            import reverse_geocoder as rg
            _geocoder = rg
            logger.info("Reverse geocoder loaded")
        except ImportError:
            logger.warning("reverse_geocoder not installed, location names unavailable")
    return _geocoder


async def geocode_photo(file_hash: str) -> bool:
    """Reverse geocode GPS coordinates for a photo."""
    async with async_session() as session:
        photo = await session.get(Photo, file_hash)
        if not photo:
            return False

        if photo.location_country or not photo.gps_latitude or not photo.gps_longitude:
            return False

        geocoder = _get_geocoder()
        if not geocoder:
            return False

        try:
            results = geocoder.search(
                [(photo.gps_latitude, photo.gps_longitude)], verbose=False
            )
            if results:
                result = results[0]
                photo.location_city = result.get("name", "")
                photo.location_country = result.get("cc", "")
                # Build a more descriptive address
                admin1 = result.get("admin1", "")
                if admin1:
                    photo.location_address = f"{photo.location_city}, {admin1}, {photo.location_country}"
                else:
                    photo.location_address = f"{photo.location_city}, {photo.location_country}"
                await session.commit()
                return True
        except Exception:
            logger.exception("Error geocoding %s", file_hash)

    return False


async def process_pending_geocoding(batch_size: int | None = None) -> int:
    """Geocode all photos that have GPS but no location names."""
    if batch_size is None:
        batch_size = settings.batch_size

    async with async_session() as session:
        result = await session.execute(
            select(Photo.file_hash)
            .where(
                Photo.gps_latitude.is_not(None),
                Photo.gps_longitude.is_not(None),
                Photo.location_country.is_(None),
                Photo.exif_extracted == True,  # noqa: E712
            )
            .limit(batch_size)
        )
        hashes = result.scalars().all()

    processed = 0
    for file_hash in hashes:
        if await geocode_photo(file_hash):
            processed += 1

    if processed:
        logger.info("Geocoded %d photos", processed)
    return processed
