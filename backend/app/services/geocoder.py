"""Reverse geocoding service - converts GPS coordinates to location names."""

import asyncio
import logging

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
        # 0.0 is a coordinate (the equator, the prime meridian), not "no GPS".
        if (
            photo.location_country
            or photo.gps_latitude is None
            or photo.gps_longitude is None
        ):
            return False
        coords = (photo.gps_latitude, photo.gps_longitude)

    geocoder = _get_geocoder()
    if not geocoder:
        return False

    try:
        # mode=1 is reverse_geocoder's single-threaded query. The default
        # (mode=2) forks worker processes and joins them, and forking a
        # process that already has ~30 threads and a running event loop
        # deadlocks: the child dies, the parent waits on join() forever and
        # takes the whole API down with it. to_thread keeps even the
        # single-threaded query off the event loop, since the KD-tree
        # lookup is CPU-bound and blocks every other request while it runs.
        results = await asyncio.to_thread(geocoder.search, [coords], 1, False)
        if not results:
            return False
        result = results[0]
        async with async_session() as session:
            photo = await session.get(Photo, file_hash)
            if not photo:
                return False
            photo.location_city = result.get("name", "")
            photo.location_country = result.get("cc", "")
            # Build a more descriptive address
            admin1 = result.get("admin1", "")
            if admin1:
                photo.location_address = (
                    f"{photo.location_city}, {admin1}, {photo.location_country}"
                )
            else:
                photo.location_address = f"{photo.location_city}, {photo.location_country}"
            await session.commit()
        return True
    except Exception as e:
        logger.warning("Geocoding failed for %s: %s", file_hash, type(e).__name__)

    return False
