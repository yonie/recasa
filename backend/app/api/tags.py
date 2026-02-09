"""Tags API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_session
from backend.app.models import Photo, Tag, PhotoTag
from backend.app.schemas.photo import PhotoPage, PhotoSummary

router = APIRouter(prefix="/api/tags", tags=["tags"])


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


@router.get("")
async def list_tags(
    session: AsyncSession = Depends(get_session),
):
    """List all tags with photo counts."""
    query = (
        select(
            Tag.tag_id,
            Tag.name,
            Tag.category,
            func.count(PhotoTag.file_hash).label("count"),
        )
        .join(PhotoTag, PhotoTag.tag_id == Tag.tag_id)
        .group_by(Tag.tag_id, Tag.name, Tag.category)
        .having(func.count(PhotoTag.file_hash) > 0)
        .order_by(func.count(PhotoTag.file_hash).desc())
    )

    result = await session.execute(query)
    rows = result.all()

    return [
        {
            "tag_id": row.tag_id,
            "name": row.name,
            "category": row.category,
            "count": row.count,
        }
        for row in rows
    ]


@router.get("/{tag_id}/photos", response_model=PhotoPage)
async def get_tag_photos(
    tag_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """Get all photos with a specific tag."""
    tag = await session.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    query = (
        select(Photo)
        .join(PhotoTag, PhotoTag.file_hash == Photo.file_hash)
        .where(PhotoTag.tag_id == tag_id)
    )

    count_query = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_query)).scalar() or 0

    offset = (page - 1) * page_size
    query = query.order_by(Photo.date_taken.desc().nullslast()).offset(offset).limit(page_size)

    result = await session.execute(query)
    photos = result.scalars().all()

    return PhotoPage(
        items=[_photo_to_summary(p) for p in photos],
        total=total,
        page=page,
        page_size=page_size,
        has_more=offset + page_size < total,
    )
