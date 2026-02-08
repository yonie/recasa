"""Photo API endpoints."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select, or_, exists
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.config import settings
from backend.app.database import get_session
from backend.app.models import Photo, PhotoTag, Tag, Face, Person, Caption
from backend.app.schemas.photo import (
    FaceSummary,
    PhotoDetail,
    PhotoExif,
    PhotoLocation,
    PhotoPage,
    PhotoSummary,
    TagSummary,
    LibraryStats,
)
from backend.app.services.thumbnail import get_thumbnail_path, generate_thumbnails

router = APIRouter(prefix="/api/photos", tags=["photos"])


def _photo_to_summary(photo: Photo) -> PhotoSummary:
    return PhotoSummary(
        file_hash=photo.file_hash,
        file_path=photo.file_path,
        file_name=photo.file_name,
        file_size=photo.file_size,
        mime_type=photo.mime_type,
        width=photo.width,
        height=photo.height,
        date_taken=photo.date_taken,
        is_favorite=photo.is_favorite,
        thumbnail_url=f"/api/photos/{photo.file_hash}/thumbnail/600",
        has_live_photo=bool(photo.live_photo_video or photo.motion_photo),
    )


@router.get("", response_model=PhotoPage)
async def list_photos(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort: str = Query("date_taken", pattern="^(date_taken|file_name|file_size|indexed_at)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    favorite: bool | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    country: str | None = None,
    city: str | None = None,
    search: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """List photos with pagination and filtering."""
    query = select(Photo)

    # Apply filters
    if favorite is not None:
        query = query.where(Photo.is_favorite == favorite)
    if date_from:
        query = query.where(Photo.date_taken >= date_from)
    if date_to:
        query = query.where(Photo.date_taken <= date_to)
    if country:
        query = query.where(Photo.location_country == country)
    if city:
        query = query.where(Photo.location_city == city)
    if search:
        search_term = f"%{search}%"
        # Search across file name, location, tags, captions, and people
        tag_match = (
            select(PhotoTag.file_hash)
            .join(Tag, Tag.tag_id == PhotoTag.tag_id)
            .where(Tag.name.ilike(search_term))
            .where(PhotoTag.file_hash == Photo.file_hash)
            .correlate(Photo)
        )
        caption_match = (
            select(Caption.file_hash)
            .where(Caption.caption.ilike(search_term))
            .where(Caption.file_hash == Photo.file_hash)
            .correlate(Photo)
        )
        person_match = (
            select(Face.file_hash)
            .join(Person, Person.person_id == Face.person_id)
            .where(Person.name.ilike(search_term))
            .where(Face.file_hash == Photo.file_hash)
            .correlate(Photo)
        )
        query = query.where(
            or_(
                Photo.file_name.ilike(search_term),
                Photo.location_city.ilike(search_term),
                Photo.location_country.ilike(search_term),
                Photo.location_address.ilike(search_term),
                exists(tag_match),
                exists(caption_match),
                exists(person_match),
            )
        )

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_query)).scalar() or 0

    # Apply sorting
    sort_col = getattr(Photo, sort, Photo.date_taken)
    if order == "desc":
        query = query.order_by(sort_col.desc().nullslast())
    else:
        query = query.order_by(sort_col.asc().nullsfirst())

    # Paginate
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    result = await session.execute(query)
    photos = result.scalars().all()

    return PhotoPage(
        items=[_photo_to_summary(p) for p in photos],
        total=total,
        page=page,
        page_size=page_size,
        has_more=offset + page_size < total,
    )


@router.get("/stats", response_model=LibraryStats)
async def get_stats(session: AsyncSession = Depends(get_session)):
    """Get library statistics."""
    total = (await session.execute(select(func.count(Photo.file_hash)))).scalar() or 0
    total_size = (await session.execute(select(func.sum(Photo.file_size)))).scalar() or 0
    total_faces = (await session.execute(select(func.count(Face.face_id)))).scalar() or 0
    total_persons = (await session.execute(select(func.count(Person.person_id)))).scalar() or 0
    total_tags = (await session.execute(select(func.count(Tag.tag_id)))).scalar() or 0
    favorites = (
        await session.execute(
            select(func.count(Photo.file_hash)).where(Photo.is_favorite == True)  # noqa: E712
        )
    ).scalar() or 0

    oldest = (
        await session.execute(
            select(func.min(Photo.date_taken)).where(Photo.date_taken.is_not(None))
        )
    ).scalar()
    newest = (
        await session.execute(
            select(func.max(Photo.date_taken)).where(Photo.date_taken.is_not(None))
        )
    ).scalar()

    locations = (
        await session.execute(
            select(func.count(func.distinct(Photo.location_city))).where(
                Photo.location_city.is_not(None)
            )
        )
    ).scalar() or 0

    return LibraryStats(
        total_photos=total,
        total_size_bytes=total_size,
        total_faces=total_faces,
        total_persons=total_persons,
        total_tags=total_tags,
        oldest_photo=oldest,
        newest_photo=newest,
        locations_count=locations,
        favorites_count=favorites,
    )


@router.get("/{file_hash}", response_model=PhotoDetail)
async def get_photo(file_hash: str, session: AsyncSession = Depends(get_session)):
    """Get detailed photo information."""
    photo = await session.get(Photo, file_hash)
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")

    # Load faces with person info
    faces_result = await session.execute(
        select(Face).where(Face.file_hash == file_hash).options(selectinload(Face.person))
    )
    faces = faces_result.scalars().all()

    face_summaries = [
        FaceSummary(
            face_id=f.face_id,
            person_id=f.person_id,
            person_name=f.person.name if f.person else None,
            bbox_x=f.bbox_x,
            bbox_y=f.bbox_y,
            bbox_w=f.bbox_w,
            bbox_h=f.bbox_h,
        )
        for f in faces
    ]

    # Load tags
    tags_result = await session.execute(
        select(PhotoTag, Tag)
        .join(Tag, PhotoTag.tag_id == Tag.tag_id)
        .where(PhotoTag.file_hash == file_hash)
    )
    tag_rows = tags_result.all()
    tag_summaries = [
        TagSummary(
            tag_id=t.tag_id,
            name=t.name,
            category=t.category,
            confidence=pt.confidence,
        )
        for pt, t in tag_rows
    ]

    # Load caption
    caption_obj = await session.get(Caption, file_hash)
    caption_text = caption_obj.caption if caption_obj else None

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
        file_modified=photo.file_modified,
        location=location,
        exif=exif,
        faces=face_summaries,
        tags=tag_summaries,
        caption=caption_text,
        live_photo_video=photo.live_photo_video,
        motion_photo=photo.motion_photo,
        thumbnail_url=f"/api/photos/{photo.file_hash}/thumbnail/600",
        indexed_at=photo.indexed_at,
    )


@router.get("/{file_hash}/thumbnail/{size}")
async def get_thumbnail(file_hash: str, size: int = 600):
    """Serve a photo thumbnail, generating on-demand if needed."""
    thumb_path = get_thumbnail_path(file_hash, size)
    if not thumb_path:
        await generate_thumbnails(file_hash)
        thumb_path = get_thumbnail_path(file_hash, size)
        if not thumb_path:
            raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(thumb_path, media_type="image/webp")


@router.get("/{file_hash}/original")
async def get_original(file_hash: str, session: AsyncSession = Depends(get_session)):
    """Serve the original photo file."""
    photo = await session.get(Photo, file_hash)
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")

    filepath = settings.photos_dir / photo.file_path
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(filepath, media_type=photo.mime_type or "application/octet-stream")


@router.get("/{file_hash}/live")
async def get_live_photo_video(file_hash: str, session: AsyncSession = Depends(get_session)):
    """Serve the Live Photo video."""
    photo = await session.get(Photo, file_hash)
    if not photo or not photo.live_photo_video:
        raise HTTPException(status_code=404, detail="Live photo video not found")

    video_path = settings.photos_dir / photo.live_photo_video
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video file not found on disk")

    return FileResponse(video_path, media_type="video/quicktime")


@router.post("/{file_hash}/favorite")
async def toggle_favorite(file_hash: str, session: AsyncSession = Depends(get_session)):
    """Toggle a photo's favorite status."""
    photo = await session.get(Photo, file_hash)
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")

    photo.is_favorite = not photo.is_favorite
    await session.commit()

    return {"file_hash": file_hash, "is_favorite": photo.is_favorite}
