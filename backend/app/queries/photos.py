"""Photo grid selects, summaries and paging."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import Photo
from backend.app.schemas.photo import PhotoPage, PhotoSummary

# Flagged-for-removal photos are hidden from every view except the Flagged
# page. Written as `== False` so it compiles to `= 0`, the form the existing
# query plans were measured with.
VISIBLE: ColumnElement[bool] = Photo.flagged_for_removal == False  # noqa: E712

# Grid orders. Undated photos sort after dated ones either way.
NEWEST_FIRST = (Photo.date_taken.desc().nullslast(),)
OLDEST_FIRST = (Photo.date_taken.asc().nullslast(),)

# Just what a grid tile needs. Selecting these columns instead of whole Photo
# entities skips the ORM identity map, which on a 40k-photo timeline was most
# of the request time.
SUMMARY_COLUMNS = (
    Photo.file_hash,
    Photo.file_path,
    Photo.file_name,
    Photo.file_size,
    Photo.mime_type,
    Photo.width,
    Photo.height,
    Photo.date_taken,
    Photo.is_favorite,
    Photo.marked_for_print,
    Photo.flagged_for_removal,
    Photo.is_video,
    Photo.duration,
    Photo.live_photo_video,
    Photo.motion_photo,
)
_N_SUMMARY_COLUMNS = len(SUMMARY_COLUMNS)


def summary_select() -> Select[Any]:
    """A select of the grid-tile columns, ready for filters and joins."""
    return select(*SUMMARY_COLUMNS)


def thumbnail_url(file_hash: str, size: int = 600) -> str:
    return f"/api/photos/{file_hash}/thumbnail/{size}"


def to_summary(row: Sequence[Any], *, full: bool = True) -> PhotoSummary:
    """Grid-tile summary from a row that starts with the SUMMARY_COLUMNS.

    ``full=False`` leaves out marked_for_print, flagged_for_removal, is_video
    and duration, so they read as their schema defaults. That is what the
    person, tag, event, place, folder, large-file, duplicate and together
    grids have always returned; the library and timeline grids are full.

    Unpacks by position: this runs once per photo, 40k times for a whole
    library timeline, and named access on rows was a third of that request.
    """
    (
        file_hash,
        file_path,
        file_name,
        file_size,
        mime_type,
        width,
        height,
        date_taken,
        is_favorite,
        marked_for_print,
        flagged_for_removal,
        is_video,
        duration,
        live_photo_video,
        motion_photo,
    ) = row[:_N_SUMMARY_COLUMNS]
    if full:
        return PhotoSummary(
            file_hash=file_hash,
            file_path=file_path,
            file_name=file_name,
            file_size=file_size,
            mime_type=mime_type,
            width=width,
            height=height,
            date_taken=date_taken,
            is_favorite=is_favorite,
            marked_for_print=marked_for_print,
            flagged_for_removal=flagged_for_removal,
            is_video=is_video,
            duration=duration,
            thumbnail_url=f"/api/photos/{file_hash}/thumbnail/600",
            has_live_photo=bool(live_photo_video or motion_photo),
        )
    return PhotoSummary(
        file_hash=file_hash,
        file_path=file_path,
        file_name=file_name,
        file_size=file_size,
        mime_type=mime_type,
        width=width,
        height=height,
        date_taken=date_taken,
        is_favorite=is_favorite,
        thumbnail_url=f"/api/photos/{file_hash}/thumbnail/600",
        has_live_photo=bool(live_photo_video or motion_photo),
    )


async def photo_page(
    session: AsyncSession,
    stmt: Select[Any],
    *,
    order_by: Sequence[Any],
    page: int,
    page_size: int,
    full: bool = True,
) -> PhotoPage:
    """Count ``stmt`` and return one page of it as grid summaries.

    ``stmt`` is a :func:`summary_select` with its filters and joins applied.
    The ordering is applied here, after counting, so the count query never
    sorts.
    """
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar()
    total = total or 0
    offset = (page - 1) * page_size
    rows = (await session.execute(stmt.order_by(*order_by).offset(offset).limit(page_size))).all()
    return PhotoPage(
        items=[to_summary(row, full=full) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        has_more=offset + page_size < total,
    )
