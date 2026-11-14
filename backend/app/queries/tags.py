"""Tag usage counts."""

from sqlalchemy import Boolean, Integer, String, TextualSelect, bindparam, text

# Per-tag photo counts over visible photos, ranked, with the number of ranked
# tags alongside every row.
#
# There are ~600k photo_tags rows. Joined the obvious way SQLite walks them in
# tag order and looks each photo up by its 64-character hash, which took over
# five seconds for the default listing. CROSS JOIN fixes the loop order in
# SQLite: walk the ~40k photos once and read each one's tags from the
# (file_hash, tag_id) primary key index, about ten times faster. The counts
# CTE is then shared by the ranking and the window total, where the previous
# version ran a second full pass just for the total.
#
# The total counts every tag id that has visible photos, also one whose tags
# row is missing, as the old COUNT(DISTINCT photo_tags.tag_id) did; such rows
# sort last and the caller drops them (`known` is false), so the items are
# exactly the inner join's top `limit`. With a name filter the missing rows
# drop out of both, again as before.
_TAG_COUNTS_SQL = """
WITH counts AS (
    SELECT photo_tags.tag_id AS tag_id, count(*) AS count
    FROM photos CROSS JOIN photo_tags ON photo_tags.file_hash = photos.file_hash
    WHERE photos.flagged_for_removal = 0
    GROUP BY photo_tags.tag_id
)
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

_RESULT_TYPES = {
    "tag_id": Integer,
    "name": String,
    "category": String,
    "count": Integer,
    "known": Boolean,
    "total": Integer,
}


def tag_counts_query(*, limit: int, name_contains: str | None = None) -> TextualSelect:
    """Top ``limit`` tags by visible-photo count (ties by name), optionally only
    tags whose name contains ``name_contains`` (case-insensitive, LIKE
    wildcards honoured, as the endpoint always has).

    Rows carry tag_id, name, category, count, known and total.
    """
    if name_contains:
        stmt = text(_TAG_COUNTS_SQL.format(where="WHERE lower(tags.name) LIKE lower(:pattern)"))
        stmt = stmt.bindparams(bindparam("pattern", f"%{name_contains}%"))
    else:
        stmt = text(_TAG_COUNTS_SQL.format(where=""))
    return stmt.bindparams(bindparam("limit", limit)).columns(**_RESULT_TYPES)
