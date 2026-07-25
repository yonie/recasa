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
        marked_for_print=photo.marked_for_print,
        flagged_for_removal=photo.flagged_for_removal,
        is_video=photo.is_video,
        duration=photo.duration,
        thumbnail_url=f"/api/photos/{photo.file_hash}/thumbnail/600",
        has_live_photo=bool(photo.live_photo_video or photo.motion_photo),
    )


@router.get("/years")
async def get_years(session: AsyncSession = Depends(get_session)):
    """Get list of years with photo counts."""
    # Use COALESCE to fall back to file_modified year when date_taken is null
    result = await session.execute(
        select(
            func.coalesce(
                extract("year", Photo.date_taken),
                extract("year", Photo.file_modified)
            ).label("year"),
            func.count(Photo.file_hash).label("count"),
        )
        .where(Photo.flagged_for_removal == False)  # noqa: E712
        .group_by(
            func.coalesce(
                extract("year", Photo.date_taken),
                extract("year", Photo.file_modified)
            )
        )
        .order_by(
            func.coalesce(
                extract("year", Photo.date_taken),
                extract("year", Photo.file_modified)
            ).desc()
        )
    )

    years = [{"year": int(row.year), "count": row.count} for row in result if row.year]

    # Four preview photos per year, evenly spaced through the year so the
    # strip reads like a mini summary (not just four January shots).
    from sqlalchemy import text

    preview_rows = await session.execute(
        text(
            """
            WITH yearly AS (
                SELECT file_hash,
                       CAST(strftime('%Y', COALESCE(date_taken, file_modified)) AS INTEGER) AS year,
                       ROW_NUMBER() OVER (
                           PARTITION BY strftime('%Y', COALESCE(date_taken, file_modified))
                           ORDER BY COALESCE(date_taken, file_modified)
                       ) AS rn,
                       COUNT(*) OVER (
                           PARTITION BY strftime('%Y', COALESCE(date_taken, file_modified))
                       ) AS cnt
                FROM photos
                WHERE COALESCE(date_taken, file_modified) IS NOT NULL
                  AND flagged_for_removal = 0
            )
            SELECT year, file_hash FROM yearly
            WHERE rn = 1 OR rn = cnt / 4 + 1 OR rn = cnt / 2 + 1 OR rn = 3 * cnt / 4 + 1
            ORDER BY year DESC, rn
            """
        )
    )
    previews: dict[int, list[str]] = {}
    for year, file_hash in preview_rows.all():
        previews.setdefault(int(year), []).append(file_hash)

    for entry in years:
        entry["previews"] = previews.get(entry["year"], [])[:4]

    return years


@router.get("", response_model=list[TimelineGroup])
async def get_timeline(
    year: int | None = None,
    month: int | None = None,
    video: bool | None = None,
    group_by: str = Query("month", pattern="^(year|month|day)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """Get photos grouped by time period."""
    query = select(Photo).where(Photo.flagged_for_removal == False)  # noqa: E712

    # Match the /years counts, which fall back to file_modified when
    # date_taken is null (common for videos without EXIF dates).
    effective_date = func.coalesce(Photo.date_taken, Photo.file_modified)
    if video is not None:
        query = query.where(Photo.is_video == video)
    if year:
        query = query.where(extract("year", effective_date) == year)
    if month:
        query = query.where(extract("month", effective_date) == month)

    query = query.order_by(Photo.date_taken.desc().nullslast(), Photo.file_modified.desc().nullslast())

    result = await session.execute(query)
    photos = result.scalars().all()

    # Group photos by the specified time period
    # Use file_modified as fallback when date_taken is null
    groups: dict[str, list[Photo]] = {}
    for photo in photos:
        date = photo.date_taken or photo.file_modified
        if not date:
            key = "unknown"
        elif group_by == "year":
            key = str(date.year)
        elif group_by == "month":
            key = f"{date.year}-{date.month:02d}"
        else:  # day
            key = date.strftime("%Y-%m-%d")

        if key not in groups:
            groups[key] = []
        groups[key].append(photo)

    # Convert to response format (apply offset/limit to groups)
    # Sort normally but put "unknown" at the end
    dated_keys = sorted([k for k in groups.keys() if k != "unknown"], reverse=True)
    sorted_keys = dated_keys + (["unknown"] if "unknown" in groups else [])
    paginated_keys = sorted_keys[offset : offset + limit]

    return [
        TimelineGroup(
            date=key,
            count=len(groups[key]),
            photos=[_photo_to_summary(p) for p in groups[key]],
        )
        for key in paginated_keys
    ]
