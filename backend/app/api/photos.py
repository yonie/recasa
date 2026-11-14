"""Photo API endpoints."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import extract, func, select, update
from sqlalchemy.orm import selectinload

from backend.app.api.deps import (
    CollageGrid,
    Page,
    PageSize,
    SessionDep,
    UntilDatetime,
    require_file_hash,
)
from backend.app.api.files import contained_path, file_response
from backend.app.api.responses import collage_response
from backend.app.config import settings
from backend.app.database import async_session
from backend.app.models import Caption, Face, Person, Photo, PhotoHash, PhotoTag, Tag
from backend.app.queries.filters import library_conditions
from backend.app.queries.photos import (
    OLDEST_FIRST,
    VISIBLE,
    photo_page,
    sorted_by,
    summary_select,
    thumbnail_url,
)
from backend.app.schemas.photo import (
    FaceSummary,
    LibraryStats,
    PhotoDetail,
    PhotoExif,
    PhotoLocation,
    PhotoPage,
)
from backend.app.services.preview import (
    needs_preview,
    preview_path,
    render_gate,
    render_preview,
)
from backend.app.services.print_export import build_print_zip
from backend.app.services.thumbnail import generate_thumbnails, get_thumbnail_path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/photos", tags=["photos"])

SortColumn = Annotated[str, Query(pattern="^(date_taken|file_name|file_size|indexed_at)$")]
SortOrder = Annotated[str, Query(pattern="^(asc|desc)$")]


@router.get("", response_model=PhotoPage)
async def list_photos(
    session: SessionDep,
    page: Page = 1,
    page_size: PageSize = 50,
    sort: SortColumn = "date_taken",
    order: SortOrder = "desc",
    favorite: bool | None = None,
    marked_for_print: bool | None = None,
    flagged: bool | None = None,
    video: bool | None = None,
    date_from: datetime | None = None,
    date_to: UntilDatetime = None,
    country: str | None = None,
    city: str | None = None,
    search: Annotated[str | None, Query(max_length=500)] = None,
):
    """List photos with pagination and filtering."""
    stmt = summary_select().where(
        *library_conditions(
            flagged=flagged,
            favorite=favorite,
            marked_for_print=marked_for_print,
            video=video,
            date_from=date_from,
            date_to=date_to,
            country=country,
            city=city,
            search=search,
        )
    )
    # Undated photos come last newest-first and first oldest-first: the one
    # order reversed.
    descending = order == "desc"
    order_by = sorted_by(getattr(Photo, sort), descending=descending, nulls_last=descending)
    return await photo_page(session, stmt, order_by=order_by, page=page, page_size=page_size)


@router.get("/stats", response_model=LibraryStats)
async def get_stats(session: SessionDep):
    """Get library statistics."""
    # Every per-photo figure in one pass over photos instead of nine queries.
    # Oldest, newest and the place count include flagged photos, as they
    # always have.
    (total, total_size, favorites, to_print, flagged, videos, oldest, newest, locations) = (
        await session.execute(
            select(
                func.count().filter(VISIBLE, Photo.is_video == False),  # noqa: E712
                func.sum(Photo.file_size).filter(VISIBLE),
                func.count().filter(Photo.is_favorite == True, VISIBLE),  # noqa: E712
                func.count().filter(Photo.marked_for_print == True, VISIBLE),  # noqa: E712
                func.count().filter(Photo.flagged_for_removal == True),  # noqa: E712
                func.count().filter(Photo.is_video == True, VISIBLE),  # noqa: E712
                func.min(Photo.date_taken),
                func.max(Photo.date_taken),
                func.count(func.distinct(Photo.location_city)),
            )
        )
    ).one()

    total_faces = (await session.execute(select(func.count(Face.face_id)))).scalar() or 0
    # Only user-named people count as "people": unnamed rows are automatic
    # face clusters (mostly single-face noise), not verified identities.
    total_persons = (
        await session.execute(
            select(func.count(Person.person_id)).where(
                Person.name.is_not(None),
                Person.name != "",
                Person.ignored == False,  # noqa: E712
            )
        )
    ).scalar() or 0
    total_tags = (await session.execute(select(func.count(Tag.tag_id)))).scalar() or 0

    return LibraryStats(
        total_photos=total or 0,
        total_size_bytes=total_size or 0,
        total_faces=total_faces,
        total_persons=total_persons,
        total_tags=total_tags,
        oldest_photo=oldest,
        newest_photo=newest,
        locations_count=locations or 0,
        favorites_count=favorites or 0,
        to_print_count=to_print or 0,
        flagged_count=flagged or 0,
        videos_count=videos or 0,
    )


@router.get("/collage")
async def get_photos_collage(
    request: Request,
    session: SessionDep,
    favorite: bool | None = None,
    year: int | None = None,
    tag: str | None = None,
    grid: CollageGrid = 0,
    seed: int = 0,
):
    """Generate a square collage from filtered photos (favorites, year, tag, etc)."""
    stmt = (
        select(Photo.file_hash, PhotoHash.phash)
        .outerjoin(PhotoHash, PhotoHash.file_hash == Photo.file_hash)
        .where(VISIBLE)
    )
    if favorite is not None:
        stmt = stmt.where(Photo.is_favorite == favorite)
    if year is not None:
        stmt = stmt.where(extract("year", Photo.date_taken) == year)
    if tag is not None:
        stmt = (
            stmt.join(PhotoTag, PhotoTag.file_hash == Photo.file_hash)
            .join(Tag, Tag.tag_id == PhotoTag.tag_id)
            .where(Tag.name == tag)
        )
    rows = (await session.execute(stmt.order_by(*OLDEST_FIRST))).all()
    return await collage_response(request, session, rows, grid, seed)


@router.get("/print/export")
async def export_print_zip(session: SessionDep):
    """Stream all photos marked for print as a flat zip (HEIC converted to JPEG)."""
    rows = (
        await session.execute(
            select(
                Photo.file_hash,
                Photo.file_path,
                Photo.file_name,
                Photo.mime_type,
                Photo.date_taken,
            )
            .where(Photo.marked_for_print == True, VISIBLE)  # noqa: E712
            .order_by(*OLDEST_FIRST)
        )
    ).all()
    if not rows:
        raise HTTPException(status_code=404, detail="No photos marked for print")

    # Downloading is the closest signal we have to "this went to a printer".
    now = datetime.now()
    await session.execute(
        update(Photo)
        .where(Photo.file_hash.in_([r.file_hash for r in rows]))
        .values(exported_at=now)
    )
    await session.commit()
    # The zip streams for as long as the download takes; it reads files only,
    # so it must not keep a pooled connection checked out meanwhile.
    await session.close()

    # A path that would lie outside the library is left out like a missing file.
    entries = [
        (path, r.file_name, r.mime_type, r.date_taken)
        for r in rows
        if (path := contained_path(settings.photos_dir, r.file_path)) is not None
    ]
    return StreamingResponse(
        build_print_zip(entries),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="to-print-{now:%Y-%m-%d}.zip"'},
    )


@router.post("/print/clear")
async def clear_print_list(session: SessionDep):
    """Remove all photos from the print list."""
    result = await session.execute(
        update(Photo)
        .where(Photo.marked_for_print == True)  # noqa: E712
        .values(marked_for_print=False)
    )
    await session.commit()
    return {"removed": result.rowcount}


def _safe_int(val) -> int | None:
    """Convert a value to int, handling numpy int64 stored as bytes in SQLite."""
    if val is None:
        return None
    if isinstance(val, bytes):
        return int.from_bytes(val, byteorder="little", signed=True)
    return int(val)


@router.get("/{file_hash}", response_model=PhotoDetail)
async def get_photo(file_hash: str, session: SessionDep):
    """Get detailed photo information."""
    require_file_hash(file_hash, "Photo not found")
    photo = await session.get(Photo, file_hash)
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")

    # Explicit orders below are the ones these lookups have always come back
    # in (index order), pinned so a new index cannot reshuffle the response.
    tag_rows = await session.execute(
        select(Tag.tag_id, Tag.name, Tag.category)
        .join(PhotoTag, PhotoTag.tag_id == Tag.tag_id)
        .where(PhotoTag.file_hash == file_hash)
        .order_by(PhotoTag.tag_id)
    )
    tags = [{"tag_id": t.tag_id, "name": t.name, "category": t.category} for t in tag_rows]

    faces = (
        await session.execute(
            select(Face)
            .where(Face.file_hash == file_hash)
            .options(selectinload(Face.person))
            .order_by(Face.face_id)
        )
    ).scalars()
    face_summaries = [
        FaceSummary(
            face_id=f.face_id,
            person_id=f.person_id,
            person_name=f.person.name if f.person else None,
            bbox_x=_safe_int(f.bbox_x),
            bbox_y=_safe_int(f.bbox_y),
            bbox_w=_safe_int(f.bbox_w),
            bbox_h=_safe_int(f.bbox_h),
        )
        for f in faces
    ]

    caption = await session.get(Caption, file_hash)

    location = None
    if photo.gps_latitude is not None:
        location = PhotoLocation(
            latitude=photo.gps_latitude,
            longitude=photo.gps_longitude,
            altitude=photo.gps_altitude,
            country=photo.location_country,
            city=photo.location_city,
            address=photo.location_address,
        )

    exif = PhotoExif(
        camera_make=photo.camera_make,
        camera_model=photo.camera_model,
        lens_model=photo.lens_model,
        focal_length=photo.focal_length,
        aperture=photo.aperture,
        shutter_speed=photo.shutter_speed,
        iso=photo.iso,
        orientation=photo.orientation,
    )

    return PhotoDetail(
        file_hash=photo.file_hash,
        file_path=photo.file_path,
        file_name=photo.file_name,
        file_size=photo.file_size,
        mime_type=photo.mime_type,
        width=photo.width,
        height=photo.height,
        date_taken=photo.date_taken,
        is_favorite=photo.is_favorite,
        marked_for_print=photo.marked_for_print,
        flagged_for_removal=photo.flagged_for_removal,
        is_video=photo.is_video,
        duration=photo.duration,
        file_modified=photo.file_modified,
        location=location,
        exif=exif,
        faces=face_summaries,
        tags=tags,
        caption=caption.caption if caption else None,
        live_photo_video=photo.live_photo_video,
        motion_photo=photo.motion_photo,
        thumbnail_url=thumbnail_url(photo.file_hash),
        indexed_at=photo.indexed_at,
    )


# On-demand thumbnail renders at once. A grid of a hundred photos the
# pipeline has not reached yet would otherwise start a hundred decodes and
# starve the Pi; the rest wait their turn instead.
_THUMBNAIL_RENDERS = 2
_thumbnail_gate: asyncio.Semaphore | None = None


def _thumbnail_render_gate() -> asyncio.Semaphore:
    global _thumbnail_gate
    if _thumbnail_gate is None:
        _thumbnail_gate = asyncio.Semaphore(_THUMBNAIL_RENDERS)
    return _thumbnail_gate


@router.get("/{file_hash}/thumbnail/{size}")
async def get_thumbnail(file_hash: str, request: Request, size: int = 600):
    """Serve a photo thumbnail, generating on-demand if needed."""
    require_file_hash(file_hash, "Thumbnail not found")
    thumb_path = get_thumbnail_path(file_hash, size)
    if not thumb_path:
        async with _thumbnail_render_gate():
            try:
                # Re-checks for the file first, so a render finished while
                # this request queued is not repeated.
                await generate_thumbnails(file_hash)
            except Exception:  # noqa: BLE001 - any decode failure is just "no thumbnail"
                raise HTTPException(status_code=404, detail="Thumbnail not found") from None
        thumb_path = get_thumbnail_path(file_hash, size)
        if not thumb_path:
            raise HTTPException(status_code=404, detail="Thumbnail not found")
    return file_response(request, thumb_path, "image/webp")


async def _photo_file(session, relative: str) -> Path:
    """The library file at ``relative``, after releasing the session.

    Raises the endpoints' usual 404 when it is missing (or would lie outside
    the library). The session goes back to the pool first because the file
    may be a long video download.
    """
    await session.close()
    filepath = contained_path(settings.photos_dir, relative)
    if filepath is None or not filepath.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    return filepath


@router.get("/{file_hash}/original")
async def get_original(file_hash: str, request: Request, session: SessionDep):
    """Serve the original photo file."""
    require_file_hash(file_hash, "Photo not found")
    photo = await session.get(Photo, file_hash)
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")
    mime_type = photo.mime_type or "application/octet-stream"
    filepath = await _photo_file(session, photo.file_path)
    return file_response(request, filepath, mime_type)


@router.get("/{file_hash}/preview")
async def get_preview(file_hash: str, request: Request):
    """Serve a browser-viewable full view of a photo.

    For formats a browser can decode this is the original file, byte for byte.
    For RAW (ORF) and HEIC it's a JPEG rendered on demand and cached; without
    it the viewer's <img> gets bytes no browser can decode.

    Takes no ``SessionDep`` session on purpose. The cache path is derived from
    the hash alone, so an already-rendered preview is served without touching
    the database at all; and on the cold path the render can queue for
    seconds, which is far too long to be parking a pooled connection.
    """
    require_file_hash(file_hash, "Photo not found")
    cached = preview_path(file_hash)
    if cached.exists():
        return file_response(request, cached, "image/jpeg")

    async with render_gate():
        # Re-check: a concurrent request may have rendered it while we queued.
        if cached.exists():
            return file_response(request, cached, "image/jpeg")

        async with async_session() as session:
            photo = await session.get(Photo, file_hash)
            if not photo:
                raise HTTPException(status_code=404, detail="Photo not found")
            file_path, mime_type = photo.file_path, photo.mime_type

        filepath = contained_path(settings.photos_dir, file_path)
        if filepath is None or not filepath.exists():
            raise HTTPException(status_code=404, detail="File not found on disk")

        if not needs_preview(filepath):
            return file_response(request, filepath, mime_type or "application/octet-stream")

        try:
            rendered = await asyncio.to_thread(render_preview, filepath, file_hash)
        except Exception as e:  # noqa: BLE001 - decoders raise anything on bad files
            logger.warning("Preview render failed for %s: %s", filepath, type(e).__name__)
            raise HTTPException(status_code=500, detail="Could not render preview") from e

    return file_response(request, rendered, "image/jpeg")


@router.get("/{file_hash}/live")
async def get_live_photo_video(file_hash: str, request: Request, session: SessionDep):
    """Serve the Live Photo video."""
    require_file_hash(file_hash, "Live photo video not found")
    photo = await session.get(Photo, file_hash)
    if not photo or not photo.live_photo_video:
        raise HTTPException(status_code=404, detail="Live photo video not found")
    try:
        video_path = await _photo_file(session, photo.live_photo_video)
    except HTTPException:
        raise HTTPException(status_code=404, detail="Video file not found on disk") from None
    return file_response(request, video_path, "video/quicktime")


async def _toggle(session, file_hash: str, field: str) -> dict:
    require_file_hash(file_hash, "Photo not found")
    photo = await session.get(Photo, file_hash)
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")
    setattr(photo, field, not getattr(photo, field))
    await session.commit()
    return {"file_hash": file_hash, field: getattr(photo, field)}


@router.post("/{file_hash}/favorite")
async def toggle_favorite(file_hash: str, session: SessionDep):
    """Toggle a photo's favorite status."""
    return await _toggle(session, file_hash, "is_favorite")


@router.post("/{file_hash}/print")
async def toggle_print(file_hash: str, session: SessionDep):
    """Toggle a photo's marked-for-print status."""
    return await _toggle(session, file_hash, "marked_for_print")


@router.post("/{file_hash}/flag")
async def toggle_flag(file_hash: str, session: SessionDep):
    """Toggle a photo's flagged-for-removal status.

    The app never deletes files: flagged photos are hidden from normal views
    and listed on the Flagged page with their paths for manual removal.
    """
    return await _toggle(session, file_hash, "flagged_for_removal")
