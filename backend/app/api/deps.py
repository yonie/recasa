"""Shared FastAPI dependencies and parameter types."""

import re
from datetime import date, datetime, time
from typing import Annotated

from fastapi import Depends, HTTPException, Query
from pydantic import BeforeValidator
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_session

SessionDep = Annotated[AsyncSession, Depends(get_session)]

Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=200)]
CollageGrid = Annotated[int, Query(ge=0, le=6)]

_FILE_HASH = re.compile(r"[0-9a-f]{64}")
_DATE_ONLY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _date_through_end_of_day(value: object) -> object:
    """A bare date as an upper bound means the whole of that day.

    Parsed as a datetime it would be midnight, so date_to=2019-12-31 left out
    everything taken on the 31st. A full datetime keeps its exact meaning.
    """
    if isinstance(value, str) and _DATE_ONLY.fullmatch(value):
        return datetime.combine(date.fromisoformat(value), time.max)
    return value


# An inclusive upper bound on a datetime: "YYYY-MM-DD" runs to the end of the
# day, any other datetime is taken as given.
UntilDatetime = Annotated[datetime | None, BeforeValidator(_date_through_end_of_day)]


def require_file_hash(file_hash: str, detail: str) -> None:
    """404 for anything that is not a SHA-256 hex digest.

    Every indexed photo is keyed by one, so nothing valid is turned away; it
    keeps a URL segment from ever being joined into a cache path unchecked.
    The detail is the one the endpoint gives for an unknown hash anyway.
    """
    if not _FILE_HASH.fullmatch(file_hash):
        raise HTTPException(status_code=404, detail=detail)

