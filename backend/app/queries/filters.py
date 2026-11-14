"""Library filters: the flag, date and place filters and the free-text search."""

import re
from datetime import datetime

from sqlalchemy import ColumnElement, and_, extract, or_, select

from backend.app.models import Caption, Face, Person, Photo, PhotoTag, Tag
from backend.app.queries.photos import VISIBLE

_MONTHS = {
    name: number
    for number, names in enumerate(
        [
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ],
        start=1,
    )
    for name in names
}


def date_search_condition(search: str) -> ColumnElement[bool] | None:
    """Capture-date filter from the year and month-name words in a search.

    "2013 august", "august 2013" and "2013" all work; every recognised word
    must match. None when the search names no year or month.
    """
    parts: list[ColumnElement[bool]] = []
    for token in re.findall(r"[a-z]+|\d{4}", search.lower()):
        if token.isdigit() and 1900 <= int(token) <= 2100:
            parts.append(extract("year", Photo.date_taken) == int(token))
        elif token in _MONTHS:
            parts.append(extract("month", Photo.date_taken) == _MONTHS[token])
    return and_(*parts) if parts else None


def text_search_condition(search: str) -> ColumnElement[bool]:
    """Match a search against names, places, captions, people, tags and dates.

    Captions, people and tags are matched as ``file_hash IN (...)`` sets rather
    than per-photo EXISTS subqueries: SQLite then builds each set once instead
    of probing three tables for every one of ~40k photos, which took a search
    from seconds to about a tenth of one. The matching rows are the same.
    """
    pattern = f"%{search}%"
    captioned = select(Caption.file_hash).where(Caption.caption.ilike(pattern))
    with_person = select(Face.file_hash).where(
        Face.person_id.in_(select(Person.person_id).where(Person.name.ilike(pattern)))
    )
    tagged = select(PhotoTag.file_hash).where(
        PhotoTag.tag_id.in_(select(Tag.tag_id).where(Tag.name.ilike(pattern)))
    )
    conditions = [
        Photo.file_name.ilike(pattern),
        Photo.file_path.ilike(pattern),
        Photo.location_city.ilike(pattern),
        Photo.location_country.ilike(pattern),
        Photo.location_address.ilike(pattern),
        Photo.file_hash.in_(captioned),
        Photo.file_hash.in_(with_person),
        Photo.file_hash.in_(tagged),
    ]
    date_condition = date_search_condition(search)
    if date_condition is not None:
        conditions.append(date_condition)
    return or_(*conditions)


def library_conditions(
    *,
    flagged: bool | None = None,
    favorite: bool | None = None,
    marked_for_print: bool | None = None,
    video: bool | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    country: str | None = None,
    city: str | None = None,
    search: str | None = None,
) -> list[ColumnElement[bool]]:
    """WHERE conditions for the library listing (``GET /api/photos``).

    Only ``flagged=True`` shows flagged photos (and only those); any other
    value lists the visible ones. Empty strings and missing dates mean "no
    filter", as they always have for this endpoint.
    """
    conditions: list[ColumnElement[bool]] = [
        (Photo.flagged_for_removal == True) if flagged else VISIBLE  # noqa: E712
    ]
    if favorite is not None:
        conditions.append(Photo.is_favorite == favorite)
    if marked_for_print is not None:
        conditions.append(Photo.marked_for_print == marked_for_print)
    if video is not None:
        conditions.append(Photo.is_video == video)
    if date_from:
        conditions.append(Photo.date_taken >= date_from)
    if date_to:
        conditions.append(Photo.date_taken <= date_to)
    if country:
        conditions.append(Photo.location_country == country)
    if city:
        conditions.append(Photo.location_city == city)
    if search:
        conditions.append(text_search_condition(search))
    return conditions
