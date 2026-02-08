"""Event auto-detection service.

Clusters photos by time proximity and location into events.
An "event" is a group of photos taken within a short time window
at the same or nearby location (e.g., a party, vacation day, wedding).
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import select, func, delete

from backend.app.database import async_session
from backend.app.models import Photo, Event, EventPhoto

logger = logging.getLogger(__name__)

# Maximum time gap between photos in the same event (hours)
EVENT_TIME_GAP_HOURS = 4

# Minimum photos to form an event
MIN_PHOTOS_PER_EVENT = 3

# Maximum distance in degrees to consider "same location"
# ~0.05 degrees ≈ 5.5km
LOCATION_PROXIMITY_DEGREES = 0.05


async def detect_events() -> int:
    """Detect events by clustering photos by time and location.

    Algorithm:
    1. Sort all photos by date_taken
    2. Walk through chronologically, starting a new event whenever
       the gap between consecutive photos exceeds EVENT_TIME_GAP_HOURS
    3. Sub-split events by location if photos jump significantly
    4. Only keep events with >= MIN_PHOTOS_PER_EVENT photos

    Returns the number of events created.
    """
    async with async_session() as session:
        # Get all photos with dates, sorted by date
        result = await session.execute(
            select(Photo)
            .where(Photo.date_taken.is_not(None))
            .order_by(Photo.date_taken.asc())
        )
        photos = result.scalars().all()

    if len(photos) < MIN_PHOTOS_PER_EVENT:
        return 0

    # Phase 1: Split by time gaps
    time_clusters: list[list[Photo]] = []
    current_cluster: list[Photo] = [photos[0]]

    for prev, curr in zip(photos[:-1], photos[1:]):
        if not prev.date_taken or not curr.date_taken:
            continue

        gap = (curr.date_taken - prev.date_taken).total_seconds() / 3600
        if gap > EVENT_TIME_GAP_HOURS:
            if len(current_cluster) >= MIN_PHOTOS_PER_EVENT:
                time_clusters.append(current_cluster)
            current_cluster = [curr]
        else:
            current_cluster.append(curr)

    if len(current_cluster) >= MIN_PHOTOS_PER_EVENT:
        time_clusters.append(current_cluster)

    # Phase 2: Sub-split by location
    final_clusters: list[list[Photo]] = []
    for cluster in time_clusters:
        sub_clusters = _split_by_location(cluster)
        for sc in sub_clusters:
            if len(sc) >= MIN_PHOTOS_PER_EVENT:
                final_clusters.append(sc)

    # Phase 3: Store events in database
    async with async_session() as session:
        # Clear existing auto-detected events
        await session.execute(delete(EventPhoto))
        await session.execute(delete(Event))

        for cluster in final_clusters:
            dates = [p.date_taken for p in cluster if p.date_taken]
            if not dates:
                continue

            start_date = min(dates)
            end_date = max(dates)

            # Determine location from most common city in cluster
            cities = [p.location_city for p in cluster if p.location_city]
            location = None
            if cities:
                # Most common city
                from collections import Counter
                most_common_city = Counter(cities).most_common(1)[0][0]
                # Find country for this city
                for p in cluster:
                    if p.location_city == most_common_city:
                        parts = [most_common_city]
                        if p.location_country:
                            parts.append(p.location_country)
                        location = ", ".join(parts)
                        break

            # Generate event name
            name = _generate_event_name(start_date, end_date, location)

            event = Event(
                name=name,
                start_date=start_date,
                end_date=end_date,
                location=location,
                photo_count=len(cluster),
            )
            session.add(event)
            await session.flush()

            for photo in cluster:
                session.add(EventPhoto(
                    event_id=event.event_id,
                    file_hash=photo.file_hash,
                ))

        await session.commit()

    logger.info("Detected %d events from %d photos", len(final_clusters), len(photos))
    return len(final_clusters)


def _split_by_location(photos: list[Photo]) -> list[list[Photo]]:
    """Split a time-based cluster further by location jumps."""
    if not photos:
        return []

    # If no GPS data, keep as single cluster
    gps_photos = [p for p in photos if p.gps_latitude is not None and p.gps_longitude is not None]
    if len(gps_photos) < 2:
        return [photos]

    clusters: list[list[Photo]] = []
    current: list[Photo] = [photos[0]]

    for prev, curr in zip(photos[:-1], photos[1:]):
        if (
            prev.gps_latitude is not None
            and curr.gps_latitude is not None
            and prev.gps_longitude is not None
            and curr.gps_longitude is not None
        ):
            lat_diff = abs(curr.gps_latitude - prev.gps_latitude)
            lon_diff = abs(curr.gps_longitude - prev.gps_longitude)

            if lat_diff > LOCATION_PROXIMITY_DEGREES or lon_diff > LOCATION_PROXIMITY_DEGREES:
                clusters.append(current)
                current = [curr]
                continue

        current.append(curr)

    clusters.append(current)
    return clusters


def _generate_event_name(start: datetime, end: datetime, location: str | None) -> str:
    """Generate a human-readable event name."""
    # Duration
    duration = end - start

    if duration < timedelta(hours=6):
        time_part = start.strftime("%b %d, %Y afternoon" if start.hour >= 12 else "%b %d, %Y morning")
    elif duration < timedelta(days=1):
        time_part = start.strftime("%b %d, %Y")
    elif duration < timedelta(days=7):
        if start.month == end.month:
            time_part = f"{start.strftime('%b %d')}-{end.strftime('%d, %Y')}"
        else:
            time_part = f"{start.strftime('%b %d')} - {end.strftime('%b %d, %Y')}"
    else:
        time_part = f"{start.strftime('%b %d')} - {end.strftime('%b %d, %Y')}"

    if location:
        return f"{location} - {time_part}"
    return time_part
