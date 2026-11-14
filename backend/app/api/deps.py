"""Shared FastAPI dependencies and parameter types."""

import re
from typing import Annotated

from fastapi import Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_session

SessionDep = Annotated[AsyncSession, Depends(get_session)]

Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=200)]
CollageGrid = Annotated[int, Query(ge=0, le=6)]

_FILE_HASH = re.compile(r"[0-9a-f]{64}")


def require_file_hash(file_hash: str, detail: str) -> None:
    """404 for anything that is not a SHA-256 hex digest.

    Every indexed photo is keyed by one, so nothing valid is turned away; it
    keeps a URL segment from ever being joined into a cache path unchecked.
    The detail is the one the endpoint gives for an unknown hash anyway.
    """
    if not _FILE_HASH.fullmatch(file_hash):
        raise HTTPException(status_code=404, detail=detail)

