"""Response builders shared by several routers."""

import asyncio
import hashlib
from collections import OrderedDict
from collections.abc import Sequence
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.files import REVALIDATE, not_modified
from backend.app.services.collage import render_collage


def json_response(content: Any) -> JSONResponse:
    """Return already-plain JSON data without FastAPI's jsonable_encoder pass.

    For a handler without a response model FastAPI walks the whole return
    value through jsonable_encoder, which was most of the time on the large
    map and trail payloads. The bytes are the same; use this only for content
    made of str, int, float, bool, None, lists and dicts.
    """
    return JSONResponse(content=content)


class CollageCache:
    """Recently rendered collages, least recently used dropped first.

    Kept in memory and bounded by total size; it starts empty on every
    restart and never touches the data directory.
    """

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self._entries: OrderedDict[str, bytes] = OrderedDict()
        self._size = 0

    def get(self, key: str) -> bytes | None:
        data = self._entries.get(key)
        if data is not None:
            self._entries.move_to_end(key)
        return data

    def put(self, key: str, data: bytes) -> None:
        if key in self._entries or len(data) > self.max_bytes:
            return
        self._entries[key] = data
        self._size += len(data)
        while self._size > self.max_bytes:
            _, dropped = self._entries.popitem(last=False)
            self._size -= len(dropped)


# A 1400 px collage JPEG is 0.1-0.6 MB, so this holds the last few dozen.
_collage_cache = CollageCache(max_bytes=24 * 1024 * 1024)


def collage_key(rows: Sequence[Sequence[Any]], grid: int, seed: int) -> str:
    """Identity of a collage: its photos and their phashes, in order, plus
    the grid and seed. Thumbnails are content-addressed and never change,
    so equal keys mean equal pictures once every tile has a thumbnail."""
    digest = hashlib.sha256(f"{grid}:{seed}".encode())
    for row in rows:
        digest.update(f"\n{row[0]}:{row[1] or ''}".encode())
    return digest.hexdigest()[:32]


def _jpeg(data: bytes, etag: str | None = None) -> Response:
    headers = {"ETag": etag, "Cache-Control": REVALIDATE} if etag else None
    return Response(content=data, media_type="image/jpeg", headers=headers)


async def collage_response(
    request: Request,
    session: AsyncSession,
    rows: Sequence[Sequence[Any]],
    grid: int,
    seed: int,
) -> Response:
    """Render rows starting ``(file_hash, phash, ...)``, in order, as a JPEG.

    Rendering reads and resizes thumbnails for a second or more on the Pi,
    so a picture whose tiles all drew is kept (in memory) and offered to the
    browser with an ETag: asking again for an unchanged collage costs one
    query and returns the kept bytes or a bodiless 304. The render needs no
    database, so the request's pooled connection is released first.
    """
    await session.close()
    if not rows:
        raise HTTPException(status_code=404, detail="No photos found")

    key = collage_key(rows, grid, seed)
    etag = f'"{key}"'
    # The ETag is only ever handed out for a complete picture, and that
    # picture is fixed by the key, so a browser holding it is up to date.
    if (unchanged := not_modified(request, etag, REVALIDATE)) is not None:
        return unchanged
    data = _collage_cache.get(key)
    if data is not None:
        return _jpeg(data, etag)

    hashes = [r[0] for r in rows]
    phashes = [r[1] for r in rows]
    data, complete = await asyncio.to_thread(render_collage, hashes, phashes, grid, seed=seed)
    if not data:
        raise HTTPException(status_code=404, detail="Could not generate collage")
    if not complete:
        # A tile had no thumbnail yet, so the picture changes once it has.
        return _jpeg(data)
    _collage_cache.put(key, data)
    return _jpeg(data, etag)
