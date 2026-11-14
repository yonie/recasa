"""Response builders shared by several routers."""

import asyncio
from collections.abc import Sequence
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse, Response
from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.services.collage import generate_collage


def json_response(content: Any) -> JSONResponse:
    """Return already-plain JSON data without FastAPI's jsonable_encoder pass.

    For a handler without a response model FastAPI walks the whole return
    value through jsonable_encoder, which was most of the time on the large
    map and trail payloads. The bytes are the same; use this only for content
    made of str, int, float, bool, None, lists and dicts.
    """
    return JSONResponse(content=content)


async def collage_response(
    session: AsyncSession,
    rows: Sequence[Row[Any]],
    grid: int,
    seed: int,
) -> Response:
    """Render rows starting ``(file_hash, phash, ...)``, in order, as a JPEG.

    The render reads and resizes thumbnails for a second or more and needs no
    database, so the request's pooled connection is released before it starts.
    """
    await session.close()
    if not rows:
        raise HTTPException(status_code=404, detail="No photos found")

    hashes = [r[0] for r in rows]
    phashes = [r[1] for r in rows]
    data = await asyncio.to_thread(generate_collage, hashes, phashes, grid, seed=seed)
    if not data:
        raise HTTPException(status_code=404, detail="Could not generate collage")
    return Response(content=data, media_type="image/jpeg")
