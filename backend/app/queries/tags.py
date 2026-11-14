"""Tag usage counts."""

from typing import Any

from sqlalchemy import (
    Boolean,
    Integer,
    String,
    TextualSelect,
    bindparam,
    select,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import Photo, PhotoTag
from backend.app.queries.filters import LIKE_ESCAPE, contains_pattern

# Ranking of tags by visible-photo count (ties by name), with the number of
# ranked tags alongside every row.
#
# The total counts every tag id that has visible photos, also one whose tags
# row is missing, as the old COUNT(DISTINCT photo_tags.tag_id) did; such rows
# sort last and the caller drops them (`known` is false), so the items are
# exactly the inner join's top `limit`. With a name filter the missing rows
# drop out of both, again as before.
_RANKING = """
SELECT counts.tag_id AS tag_id,
       tags.name AS name,
       tags.category AS category,
       counts.count AS count,
       tags.tag_id IS NOT NULL AS known,
       count(*) OVER () AS total
FROM counts LEFT JOIN tags ON tags.tag_id = counts.tag_id
{where}
ORDER BY tags.tag_id IS NULL, counts.count DESC, tags.name ASC
LIMIT :limit
"""

# Counts per tag over all ~600k photo_tags rows come straight off the
# (tag_id) index in tag order, which is cheap. The few photo_tags rows that
# must not count (those of flagged photos, or of photos no longer indexed)
# are counted separately through the (file_hash, tag_id) key and subtracted.
_BY_SUBTRACTION = """
WITH everything AS (
    SELECT tag_id, count(*) AS n FROM photo_tags GROUP BY tag_id
),
hidden AS (
    SELECT tag_id, count(*) AS n FROM photo_tags
    WHERE file_hash IN :hidden_hashes
    GROUP BY tag_id
),
counts AS (
    SELECT everything.tag_id AS tag_id, everything.n - coalesce(hidden.n, 0) AS count
    FROM everything LEFT JOIN hidden ON hidden.tag_id = everything.tag_id
    WHERE everything.n - coalesce(hidden.n, 0) > 0
)
"""

# Fallback when many photos are hidden: join every photo_tags row to its
# photo. CROSS JOIN fixes SQLite's loop order to walk the ~40k photos once,
# reading each one's tags from the (file_hash, tag_id) key; joined the
# obvious way it walked the tags and looked up a photo per row, 5 s here.
_BY_JOIN = """
WITH counts AS (
    SELECT photo_tags.tag_id AS tag_id, count(*) AS count
    FROM photos CROSS JOIN photo_tags ON photo_tags.file_hash = photos.file_hash
    WHERE photos.flagged_for_removal = 0
    GROUP BY photo_tags.tag_id
)
"""

# Above this many hidden photos the subtraction's IN list stops paying off.
_MAX_HIDDEN = 500

_RESULT_TYPES = {
    "tag_id": Integer,
    "name": String,
    "category": String,
    "count": Integer,
    "known": Boolean,
    "total": Integer,
}


def tag_counts_query(
    *,
    limit: int,
    name_contains: str | None = None,
    hidden_hashes: list[str] | None = None,
) -> TextualSelect:
    """Top ``limit`` tags by visible-photo count, ties by name.

    ``name_contains`` keeps tags whose name contains it (case-insensitive,
    "_" and "%" taken literally). With
    ``hidden_hashes`` (every tagged hash that is flagged or has no photo)
    counts are computed by subtraction, otherwise by the join.
    Rows carry tag_id, name, category, count, known and total.
    """
    where = (
        f"WHERE lower(tags.name) LIKE lower(:pattern) ESCAPE '{LIKE_ESCAPE}'"
        if name_contains
        else ""
    )
    if hidden_hashes is None:
        stmt = text(_BY_JOIN + _RANKING.format(where=where))
    else:
        stmt = text(_BY_SUBTRACTION + _RANKING.format(where=where)).bindparams(
            bindparam("hidden_hashes", hidden_hashes, expanding=True)
        )
    if name_contains:
        stmt = stmt.bindparams(bindparam("pattern", contains_pattern(name_contains)))
    return stmt.bindparams(bindparam("limit", limit)).columns(**_RESULT_TYPES)


async def hidden_tagged_hashes(session: AsyncSession) -> list[str] | None:
    """Hashes in photo_tags whose rows must not count: flagged photos and
    photos no longer indexed. None when there are too many for the
    subtraction to be worth it."""
    flagged = set(
        (
            await session.execute(
                select(Photo.file_hash).where(Photo.flagged_for_removal != False)  # noqa: E712
            )
        ).scalars()
    )
    if len(flagged) > _MAX_HIDDEN:
        return None
    # Two index-only scans and a set difference: cheaper than asking SQLite
    # for the anti-join, which probes the photos key once per tagged hash.
    tagged = set((await session.execute(select(PhotoTag.file_hash).distinct())).scalars())
    tagged.difference_update((await session.execute(select(Photo.file_hash))).scalars())
    hidden = flagged | tagged
    if len(hidden) > _MAX_HIDDEN:
        return None
    return sorted(hidden)


async def tag_counts(
    session: AsyncSession, *, limit: int, name_contains: str | None = None
) -> list[Any]:
    """Rows of :func:`tag_counts_query`, by the fastest route that applies."""
    hidden = await hidden_tagged_hashes(session)
    query = tag_counts_query(limit=limit, name_contains=name_contains, hidden_hashes=hidden)
    return list((await session.execute(query)).all())
