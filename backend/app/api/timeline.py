"""Timeline API endpoints."""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import extract, func, select, text

from backend.app.api.deps import SessionDep
from backend.app.api.responses import json_response
from backend.app.models import Photo
from backend.app.queries.photos import VISIBLE, summary_select, to_summary
from backend.app.schemas.photo import TimelineGroup

router = APIRouter(prefix="/api/timeline", tags=["timeline"])

# Undated photos fall back to the file's modification time everywhere on the
# timeline, so the year counts and the grouped photos agree.
_EFFECTIVE_DATE = func.coalesce(Photo.date_taken, Photo.file_modified)
_EFFECTIVE_YEAR = func.coalesce(
    extract("year", Photo.date_taken), extract("year", Photo.file_modified)
)

# Four preview photos per year, evenly spaced through the year so the strip
# reads like a mini summary (not just four January shots).
_YEAR_PREVIEWS_SQL = text(
    """
    WITH yearly AS (
        SELECT file_hash,
               CAST(strftime('%Y', COALESCE(date_taken, file_modified)) AS INTEGER) AS year,
               ROW_NUMBER() OVER (
                   PARTITION BY strftime('%Y', COALESCE(date_taken, file_modified))
                   ORDER BY COALESCE(date_taken, file_modified), file_hash
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


@router.get("/years")
async def get_years(session: SessionDep):
    """Get list of years with photo counts."""
    result = await session.execute(
        select(_EFFECTIVE_YEAR.label("year"), func.count(Photo.file_hash).label("count"))
        .where(VISIBLE)
        .group_by(_EFFECTIVE_YEAR)
        .order_by(_EFFECTIVE_YEAR.desc())
    )
    years = [{"year": int(row.year), "count": row.count} for row in result if row.year]

    previews: dict[int, list[str]] = {}
    for year, file_hash in await session.execute(_YEAR_PREVIEWS_SQL):
        previews.setdefault(int(year), []).append(file_hash)

    for entry in years:
        entry["previews"] = previews.get(entry["year"], [])[:4]

    return json_response(years)


def _group_key(date: datetime | None, group_by: str) -> str:
    if not date:
        return "unknown"
    if group_by == "year":
        return str(date.year)
    if group_by == "month":
        return f"{date.year}-{date.month:02d}"
    return date.strftime("%Y-%m-%d")


# Bounded IN lists when fetching the photos of the requested groups
_FETCH_CHUNK = 500


async def _summary_rows(
    session, conditions: list[Any], hashes: list[str], total: int
) -> dict[str, Any]:
    """Grid-tile rows by hash for ``hashes``, a subset of the ``total`` photos
    matching ``conditions``."""
    if len(hashes) * 2 > total:
        # Most of the timeline: one filtered pass beats many lookups.
        rows = await session.execute(summary_select().where(*conditions))
        return {row[0]: row for row in rows}
    found: dict[str, Any] = {}
    for start in range(0, len(hashes), _FETCH_CHUNK):
        chunk = hashes[start : start + _FETCH_CHUNK]
        for row in await session.execute(summary_select().where(Photo.file_hash.in_(chunk))):
            found[row[0]] = row
    return found


@router.get("", response_model=list[TimelineGroup])
async def get_timeline(
    session: SessionDep,
    year: int | None = None,
    month: int | None = None,
    video: bool | None = None,
    group_by: Annotated[str, Query(pattern="^(year|month|day)$")] = "month",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Get photos grouped by time period."""
    conditions = [VISIBLE]
    if video is not None:
        conditions.append(Photo.is_video == video)
    if year:
        conditions.append(extract("year", _EFFECTIVE_DATE) == year)
    if month:
        conditions.append(extract("month", _EFFECTIVE_DATE) == month)
    query = (
        select(Photo.file_hash, Photo.date_taken, Photo.file_modified)
        .where(*conditions)
        .order_by(
            Photo.date_taken.desc().nullslast(),
            Photo.file_modified.desc().nullslast(),
            Photo.file_hash.desc(),
        )
    )

    # Group every matching photo by period using only its dates, in timeline
    # order. The home page asks for 24 months of a 40k-photo library, so the
    # full tile data is then fetched just for the photos of the requested
    # groups instead of for the whole library.
    groups: dict[str, list[str]] = {}
    total = 0
    for file_hash, date_taken, file_modified in await session.execute(query):
        groups.setdefault(_group_key(date_taken or file_modified, group_by), []).append(file_hash)
        total += 1

    # Newest group first, with "unknown" (no date at all) at the end
    dated_keys = sorted((k for k in groups if k != "unknown"), reverse=True)
    sorted_keys = dated_keys + (["unknown"] if "unknown" in groups else [])
    page_keys = sorted_keys[offset : offset + limit]

    wanted = [h for key in page_keys for h in groups[key]]
    rows = await _summary_rows(session, conditions, wanted, total)
    # A photo deleted between the two queries is simply left out.
    return [
        TimelineGroup(
            date=key,
            count=len(groups[key]),
            photos=[to_summary(rows[h]) for h in groups[key] if h in rows],
        )
        for key in page_keys
    ]
