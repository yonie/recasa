"""Serving files from disk: path containment and HTTP caching."""

import hashlib
import os
from pathlib import Path

from fastapi import Request
from fastapi.responses import FileResponse, Response

# Content addressed by file_hash is immutable, so it may be cached for a year.
IMMUTABLE_CACHE = "public, max-age=31536000, immutable"
# For a URL whose content can change (a person's face, a collage): the
# browser keeps a copy but asks first, and gets a bodiless 304 if unchanged.
REVALIDATE = "no-cache"


def contained_path(base: Path, relative: str) -> Path | None:
    """``base / relative``, or None if that would leave ``base``.

    Checked lexically, without resolving symlinks: a library may well link
    in folders from elsewhere, and those are its own content. What this
    stops is a stored path that is absolute or climbs out with "..", which
    the scanner never writes but nothing else rules out.
    """
    if "\x00" in relative:
        return None
    root = os.path.normpath(base)
    candidate = os.path.normpath(os.path.join(root, relative))
    if candidate == root or os.path.commonpath([root, candidate]) != root:
        return None
    return Path(candidate)


def _etag(stat: os.stat_result) -> str:
    # Same recipe as Starlette's FileResponse, so the ETag a browser holds
    # from an earlier full response matches.
    base = f"{stat.st_mtime}-{stat.st_size}"
    return f'"{hashlib.md5(base.encode(), usedforsecurity=False).hexdigest()}"'


def not_modified(request: Request, etag: str, cache_control: str) -> Response | None:
    """A 304 response if the request already holds ``etag``, else None."""
    held = request.headers.get("if-none-match")
    if held and (held.strip() == "*" or etag in (t.strip() for t in held.split(","))):
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": cache_control})
    return None


def file_response(
    request: Request,
    path: Path,
    media_type: str,
    cache_control: str = IMMUTABLE_CACHE,
) -> Response:
    """Serve ``path`` with caching headers, answering a matching
    If-None-Match with 304 instead of the bytes."""
    try:
        stat = path.stat()
    except OSError:
        stat = None
    if stat is not None:
        etag = _etag(stat)
        if (unchanged := not_modified(request, etag, cache_control)) is not None:
            return unchanged
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Cache-Control": cache_control},
        stat_result=stat,
    )
