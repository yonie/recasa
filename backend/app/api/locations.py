"""Locations API endpoints."""

from datetime import date

from fastapi import APIRouter
from sqlalchemy import func, select

from backend.app.api.deps import Page, PageSize, SessionDep
from backend.app.api.responses import json_response
from backend.app.models import Photo
from backend.app.queries.photos import (
    NEWEST_FIRST,
    VISIBLE,
    photo_page,
    summary_select,
    thumbnail_url,
)
from backend.app.schemas.photo import PhotoPage

router = APIRouter(prefix="/api/locations", tags=["locations"])

# Map points and trail stops group photos on a grid of this many decimal
# degrees (2 places is about 1.1 km).
CLUSTER_PRECISION = 2
MAX_PHOTOS_PER_STOP = 4


@router.get("/countries")
async def list_countries(session: SessionDep):
    """List all countries with photo counts."""
    result = await session.execute(
        select(Photo.location_country, func.count(Photo.file_hash).label("count"))
        .where(Photo.location_country.is_not(None), VISIBLE)
        .group_by(Photo.location_country)
        .order_by(func.count(Photo.file_hash).desc())
    )
    return [{"country": row.location_country, "count": row.count} for row in result]


@router.get("/cities")
async def list_cities(session: SessionDep, country: str | None = None):
    """List all cities with photo counts, optionally filtered by country."""
    query = (
        select(
            Photo.location_city,
            Photo.location_country,
            func.count(Photo.file_hash).label("count"),
        )
        .where(Photo.location_city.is_not(None), VISIBLE)
        .group_by(Photo.location_city, Photo.location_country)
        .order_by(func.count(Photo.file_hash).desc())
    )
    if country:
        query = query.where(Photo.location_country == country)

    result = await session.execute(query)
    return [
        {"city": row.location_city, "country": row.location_country, "count": row.count}
        for row in result
    ]


def _grid_key(latitude: float, longitude: float) -> str:
    return f"{round(latitude, CLUSTER_PRECISION)},{round(longitude, CLUSTER_PRECISION)}"


@router.get("/map-points")
async def get_map_points(session: SessionDep):
    """Get all photos with GPS coordinates for map display.

    Returns clustered points with representative photo for each cluster.
    For large libraries, photos at the same approximate location are grouped.
    """
    rows = await session.execute(
        select(
            Photo.file_hash,
            Photo.gps_latitude,
            Photo.gps_longitude,
            Photo.location_city,
            Photo.location_country,
        )
        .where(Photo.gps_latitude.is_not(None), Photo.gps_longitude.is_not(None), VISIBLE)
        .order_by(*NEWEST_FIRST)
    )

    # The newest photo in each grid cell represents it.
    clusters: dict[str, dict] = {}
    for file_hash, lat, lon, city, country in rows:
        key = _grid_key(lat, lon)
        cluster = clusters.get(key)
        if cluster is None:
            cluster = clusters[key] = {
                "latitude": lat,
                "longitude": lon,
                "count": 0,
                "representative_hash": file_hash,
                "city": city,
                "country": country,
                "thumbnail_url": thumbnail_url(file_hash, 200),
            }
        cluster["count"] += 1

    return json_response(list(clusters.values()))


@router.get("/trail")
async def get_trail(
    session: SessionDep,
    date_from: date | None = None,
    date_to: date | None = None,
):
    """Get chronological trail of geotagged photos grouped by day and location.

    Returns stops ordered by date, each with a few representative photos.
    Used by the map "play" mode to animate a journey through photo history.
    """
    query = (
        select(
            Photo.file_hash,
            Photo.gps_latitude,
            Photo.gps_longitude,
            Photo.location_city,
            Photo.location_country,
            Photo.date_taken,
        )
        .where(
            Photo.gps_latitude.is_not(None),
            Photo.gps_longitude.is_not(None),
            Photo.date_taken.is_not(None),
            VISIBLE,
        )
        .order_by(Photo.date_taken.asc())
    )
    if date_from:
        query = query.where(Photo.date_taken >= date_from.isoformat())
    if date_to:
        query = query.where(Photo.date_taken < (date_to.isoformat() + "T23:59:59"))

    # Group by day + approximate location
    stops: dict[str, dict] = {}
    for file_hash, lat, lon, city, country, taken in await session.execute(query):
        day = taken.strftime("%Y-%m-%d")
        key = f"{day}|{_grid_key(lat, lon)}"
        stop = stops.get(key)
        if stop is None:
            stop = stops[key] = {
                "date": day,
                "latitude": lat,
                "longitude": lon,
                "city": city,
                "country": country,
                "photos": [],
                "total_count": 0,
            }
        stop["total_count"] += 1
        if len(stop["photos"]) < MAX_PHOTOS_PER_STOP:
            stop["photos"].append(
                {"file_hash": file_hash, "thumbnail_url": thumbnail_url(file_hash, 200)}
            )

    return json_response(sorted(stops.values(), key=lambda s: s["date"]))


@router.get("/photos", response_model=PhotoPage)
async def get_location_photos(
    session: SessionDep,
    country: str | None = None,
    city: str | None = None,
    page: Page = 1,
    page_size: PageSize = 50,
):
    """Get photos from a specific location."""
    stmt = summary_select().where(Photo.location_city.is_not(None), VISIBLE)
    if country:
        stmt = stmt.where(Photo.location_country == country)
    if city:
        stmt = stmt.where(Photo.location_city == city)
    return await photo_page(
        session, stmt, order_by=NEWEST_FIRST, page=page, page_size=page_size
    )
