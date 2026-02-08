"""Locations API endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_session
from backend.app.models import Photo
from backend.app.schemas.photo import PhotoPage, PhotoSummary

router = APIRouter(prefix="/api/locations", tags=["locations"])


def _photo_to_summary(photo: Photo) -> PhotoSummary:
    return PhotoSummary(
        file_hash=photo.file_hash,
        file_path=photo.file_path,
        file_name=photo.file_name,
        file_size=photo.file_size,
        mime_type=photo.mime_type,
        width=photo.width,
        height=photo.height,
        date_taken=photo.date_taken,
        is_favorite=photo.is_favorite,
        thumbnail_url=f"/api/photos/{photo.file_hash}/thumbnail/600",
        has_live_photo=bool(photo.live_photo_video or photo.motion_photo),
    )


class LocationCluster:
    """Not a Pydantic model - just used internally."""
    pass


@router.get("/countries")
async def list_countries(session: AsyncSession = Depends(get_session)):
    """List all countries with photo counts."""
    result = await session.execute(
        select(
            Photo.location_country,
            func.count(Photo.file_hash).label("count"),
        )
        .where(Photo.location_country.is_not(None))
        .group_by(Photo.location_country)
        .order_by(func.count(Photo.file_hash).desc())
    )
    return [
        {"country": row.location_country, "count": row.count}
        for row in result.all()
    ]


@router.get("/cities")
async def list_cities(
    country: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """List all cities with photo counts, optionally filtered by country."""
    query = (
        select(
            Photo.location_city,
            Photo.location_country,
            func.count(Photo.file_hash).label("count"),
        )
        .where(Photo.location_city.is_not(None))
        .group_by(Photo.location_city, Photo.location_country)
        .order_by(func.count(Photo.file_hash).desc())
    )

    if country:
        query = query.where(Photo.location_country == country)

    result = await session.execute(query)
    return [
        {
            "city": row.location_city,
            "country": row.location_country,
            "count": row.count,
        }
        for row in result.all()
    ]


@router.get("/map-points")
async def get_map_points(
    session: AsyncSession = Depends(get_session),
):
    """Get all photos with GPS coordinates for map display.

    Returns clustered points with representative photo for each cluster.
    For large libraries, photos at the same approximate location are grouped.
    """
    result = await session.execute(
        select(
            Photo.file_hash,
            Photo.file_name,
            Photo.gps_latitude,
            Photo.gps_longitude,
            Photo.location_city,
            Photo.location_country,
            Photo.date_taken,
        )
        .where(
            Photo.gps_latitude.is_not(None),
            Photo.gps_longitude.is_not(None),
        )
        .order_by(Photo.date_taken.desc().nullslast())
    )
    rows = result.all()

    # Simple grid-based clustering for map display
    # Group photos within ~1km of each other
    CLUSTER_PRECISION = 2  # decimal places (~1.1km resolution)
    clusters: dict[str, dict] = {}

    for row in rows:
        lat_key = round(row.gps_latitude, CLUSTER_PRECISION)
        lon_key = round(row.gps_longitude, CLUSTER_PRECISION)
        key = f"{lat_key},{lon_key}"

        if key not in clusters:
            clusters[key] = {
                "latitude": row.gps_latitude,
                "longitude": row.gps_longitude,
                "count": 0,
                "representative_hash": row.file_hash,
                "city": row.location_city,
                "country": row.location_country,
                "thumbnail_url": f"/api/photos/{row.file_hash}/thumbnail/200",
            }
        clusters[key]["count"] += 1

    return list(clusters.values())


@router.get("/photos", response_model=PhotoPage)
async def get_location_photos(
    country: str | None = None,
    city: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """Get photos from a specific location."""
    query = select(Photo).where(Photo.location_city.is_not(None))

    if country:
        query = query.where(Photo.location_country == country)
    if city:
        query = query.where(Photo.location_city == city)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_query)).scalar() or 0

    offset = (page - 1) * page_size
    query = query.order_by(Photo.date_taken.desc().nullslast()).offset(offset).limit(page_size)

    result = await session.execute(query)
    photos = result.scalars().all()

    return PhotoPage(
        items=[_photo_to_summary(p) for p in photos],
        total=total,
        page=page,
        page_size=page_size,
        has_more=offset + page_size < total,
    )
