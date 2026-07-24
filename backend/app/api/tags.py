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
    limit: int = Query(300, ge=1, le=1000),
    q: str | None = Query(None, max_length=100),
    session: AsyncSession = Depends(get_session),
):
    """List the most-used tags (optionally filtered by name), with photo counts.

    AI tagging produces tens of thousands of tags; returning them all made
    this endpoint a multi-MB response and the page a 74k-button DOM. Clients
    get the top `limit` by count plus the total, and search server-side.
    """
    counts = (
        select(
            PhotoTag.tag_id,
            func.count(PhotoTag.file_hash).label("count"),
        )
        .group_by(PhotoTag.tag_id)
        .subquery()
    )

    query = (
        select(Tag.tag_id, Tag.name, Tag.category, counts.c.count)
        .join(counts, counts.c.tag_id == Tag.tag_id)
        .order_by(counts.c.count.desc(), Tag.name.asc())
        .limit(limit)
    )
    total_query = select(func.count(func.distinct(PhotoTag.tag_id)))
    if q:
        pattern = f"%{q}%"
        query = query.where(Tag.name.ilike(pattern))
        total_query = (
            select(func.count(func.distinct(PhotoTag.tag_id)))
            .join(Tag, Tag.tag_id == PhotoTag.tag_id)
            .where(Tag.name.ilike(pattern))
        )

    total = (await session.execute(total_query)).scalar() or 0
    result = await session.execute(query)

    return {
        "items": [
            {
                "tag_id": row.tag_id,
                "name": row.name,
                "category": row.category,
                "count": row.count,
            }
            for row in result.all()
        ],
        "total": total,
    }


@router.get("/{tag_id}")
async def get_tag(tag_id: int, session: AsyncSession = Depends(get_session)):
    """Get a single tag with its photo count."""
    tag = await session.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    count = (
        await session.execute(
            select(func.count(PhotoTag.file_hash)).where(PhotoTag.tag_id == tag_id)
        )
    ).scalar() or 0

    return {"tag_id": tag.tag_id, "name": tag.name, "category": tag.category, "count": count}


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
