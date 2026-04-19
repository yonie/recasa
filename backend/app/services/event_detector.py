"""Event auto-detection service.

Clusters photos by time proximity and location into events.
An "event" is a group of photos taken within a short time window
at the same or nearby location (e.g., a party, vacation day, wedding).
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import select, func, delete

from backend.app.database import async_session
from backend.app.models import Photo, Event, EventPhoto, Face

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
            .where(Photo.date_source == "exif")
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

    # Fetch face data per photo for cover photo selection
    all_hashes = {p.file_hash for cluster in final_clusters for p in cluster}
    face_counts: dict[str, int] = {}
    face_positions: dict[str, list[tuple[int, int, int, int]]] = {}
    if all_hashes:
        async with async_session() as session:
            result = await session.execute(
                select(Face.file_hash, Face.bbox_x, Face.bbox_y, Face.bbox_w, Face.bbox_h)
                .where(Face.file_hash.in_(all_hashes), Face.encoding.is_not(None))
            )
            for file_hash, bx, by, bw, bh in result.all():
                face_counts[file_hash] = face_counts.get(file_hash, 0) + 1
                if bx is not None and by is not None and bw is not None and bh is not None:
                    face_positions.setdefault(file_hash, []).append((bx, by, bw, bh))

    # Phase 3: Merge nearby consecutive events into "trips"
    # Events within 36h and ~50km of each other are the same trip/holiday.
    final_clusters = _merge_nearby_events(final_clusters)

    # Phase 4: Store events in database
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

            # Generate event name and pick cover photo
            name = _generate_event_name(start_date, end_date, location)
            cover_hash = _pick_cover_photo(cluster, face_counts, face_positions)

            event = Event(
                name=name,
                start_date=start_date,
                end_date=end_date,
                location=location,
                photo_count=len(cluster),
                cover_file_hash=cover_hash,
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


# Maximum hours between consecutive events to consider merging
MERGE_TIME_GAP_HOURS = 36

# Maximum distance in degrees for merge (~0.5 degrees ≈ 55km)
MERGE_LOCATION_DEGREES = 0.5

# Maximum duration of a merged event (4 days splits a typical holiday into ~2 parts)
MAX_EVENT_DAYS = 4


def _cluster_centroid(cluster: list[Photo]) -> tuple[float | None, float | None]:
    """Average GPS coordinates of photos with location data."""
    lats = [p.gps_latitude for p in cluster if p.gps_latitude is not None]
    lons = [p.gps_longitude for p in cluster if p.gps_longitude is not None]
    if not lats or not lons:
        return None, None
    return sum(lats) / len(lats), sum(lons) / len(lons)


def _merge_nearby_events(clusters: list[list[Photo]]) -> list[list[Photo]]:
    """Merge consecutive events that are close in time and location.

    This turns per-half-day fine-grained events into multi-day trip events.
    """
    if len(clusters) < 2:
        return clusters

    merged: list[list[Photo]] = [clusters[0]]

    for cluster in clusters[1:]:
        prev = merged[-1]

        # Time check: gap between end of previous and start of current
        prev_dates = [p.date_taken for p in prev if p.date_taken]
        curr_dates = [p.date_taken for p in cluster if p.date_taken]
        if not prev_dates or not curr_dates:
            merged.append(cluster)
            continue

        gap_hours = (min(curr_dates) - max(prev_dates)).total_seconds() / 3600
        if gap_hours > MERGE_TIME_GAP_HOURS:
            merged.append(cluster)
            continue

        # Duration check: merged event wouldn't be too long
        all_dates = prev_dates + curr_dates
        span_days = (max(all_dates) - min(all_dates)).days
        if span_days > MAX_EVENT_DAYS:
            merged.append(cluster)
            continue

        # Location check: both clusters have GPS and are within range
        prev_lat, prev_lon = _cluster_centroid(prev)
        curr_lat, curr_lon = _cluster_centroid(cluster)

        if prev_lat is not None and curr_lat is not None:
            lat_diff = abs(curr_lat - prev_lat)
            lon_diff = abs(curr_lon - prev_lon)
            if lat_diff > MERGE_LOCATION_DEGREES or lon_diff > MERGE_LOCATION_DEGREES:
                merged.append(cluster)
                continue

        # Merge: either both are nearby or one has no GPS (assume same trip)
        merged[-1] = prev + cluster

    return merged


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


def _pick_cover_photo(
    photos: list[Photo],
    face_counts: dict[str, int],
    face_positions: dict[str, list[tuple[int, int, int, int]]],
) -> str:
    """Pick the best cover photo for an event.

    Scoring heuristic:
    - Prefer landscape orientation (wider photos look better as covers)
    - Prefer photos with faces (more interesting)
    - Penalize photos where faces are near the top/bottom edge (they get
      cropped by the 16:9 aspect-video display)
    - Prefer higher resolution
    - Prefer photos from the middle of the event (more representative)
    """
    if len(photos) == 1:
        return photos[0].file_hash

    mid = len(photos) // 2
    best_hash = photos[0].file_hash
    best_score = -1.0

    for i, photo in enumerate(photos):
        score = 0.0
        w = photo.width or 0
        h = photo.height or 0

        # Landscape bonus (strong — landscape photos fill the card much better)
        if w > h and h > 0:
            score += 4
        elif h > w:
            score -= 2  # penalize portrait

        # Face bonus
        faces = face_counts.get(photo.file_hash, 0)
        score += min(faces, 3) * 3

        # Face position bonus: prefer faces in the vertical middle third.
        # The event card crops to 16:9 centered, so faces in the top/bottom
        # ~25% of the image get cut off.
        bboxes = face_positions.get(photo.file_hash, [])
        if bboxes and h > 0:
            # Average vertical center of all faces (0.0=top, 1.0=bottom)
            avg_center_y = sum(
                (by + bh / 2) / h for _, by, _, bh in bboxes
            ) / len(bboxes)
            # Best score when faces are centered (0.5), worst at edges
            centeredness = 1.0 - 2.0 * abs(avg_center_y - 0.5)
            score += centeredness * 4  # strong signal

        # Resolution bonus
        if w and h:
            score += min(w * h / 5_000_000, 2)

        # Middle-of-event bonus
        distance_from_mid = abs(i - mid) / max(len(photos), 1)
        score += (1 - distance_from_mid) * 1.5

        if score > best_score:
            best_score = score
            best_hash = photo.file_hash

    return best_hash


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
