"""Timeline API endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_session
from backend.app.models import Photo
from backend.app.schemas.photo import PhotoSummary, TimelineGroup

router = APIRouter(prefix="/api/timeline", tags=["timeline"])


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


@router.get("/years")
async def get_years(session: AsyncSession = Depends(get_session)):
    """Get list of years with photo counts."""
    result = await session.execute(
        select(
            extract("year", Photo.date_taken).label("year"),
            func.count(Photo.file_hash).label("count"),
        )
        .where(Photo.date_taken.is_not(None))
        .group_by(extract("year", Photo.date_taken))
        .order_by(extract("year", Photo.date_taken).desc())
    )

    return [{"year": int(row.year), "count": row.count} for row in result]


@router.get("", response_model=list[TimelineGroup])
async def get_timeline(
    year: int | None = None,
    month: int | None = None,
    group_by: str = Query("month", pattern="^(year|month|day)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """Get photos grouped by time period."""
    query = select(Photo).where(Photo.date_taken.is_not(None))

    if year:
        query = query.where(extract("year", Photo.date_taken) == year)
    if month:
        query = query.where(extract("month", Photo.date_taken) == month)

    query = query.order_by(Photo.date_taken.desc())

    result = await session.execute(query)
    photos = result.scalars().all()

    # Group photos by the specified time period
    groups: dict[str, list[Photo]] = {}
    for photo in photos:
        if not photo.date_taken:
            continue

        if group_by == "year":
            key = str(photo.date_taken.year)
        elif group_by == "month":
            key = f"{photo.date_taken.year}-{photo.date_taken.month:02d}"
        else:  # day
            key = photo.date_taken.strftime("%Y-%m-%d")

        if key not in groups:
            groups[key] = []
        groups[key].append(photo)

    # Convert to response format (apply offset/limit to groups)
    sorted_keys = sorted(groups.keys(), reverse=True)
    paginated_keys = sorted_keys[offset : offset + limit]

    return [
        TimelineGroup(
            date=key,
            count=len(groups[key]),
            photos=[_photo_to_summary(p) for p in groups[key]],
        )
        for key in paginated_keys
    ]
