"""Duplicate and large file finder API endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_session
from backend.app.models import Photo, DuplicateGroup, DuplicateMember
from backend.app.schemas.photo import DuplicateGroupSummary, PhotoPage, PhotoSummary

router = APIRouter(prefix="/api", tags=["utilities"])


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


@router.get("/duplicates", response_model=list[DuplicateGroupSummary])
async def get_duplicates(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    """Get duplicate photo groups."""
    # Get groups with their members
    groups_query = (
        select(DuplicateGroup)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    groups_result = await session.execute(groups_query)
    groups = groups_result.scalars().all()

    result = []
    for group in groups:
        members_query = (
            select(Photo)
            .join(DuplicateMember, DuplicateMember.file_hash == Photo.file_hash)
            .where(DuplicateMember.group_id == group.group_id)
        )
        members_result = await session.execute(members_query)
        photos = members_result.scalars().all()

        result.append(
            DuplicateGroupSummary(
                group_id=group.group_id,
                photos=[_photo_to_summary(p) for p in photos],
            )
        )

    return result


@router.get("/large-files", response_model=PhotoPage)
async def get_large_files(
    min_size: int = Query(10_000_000, ge=0, description="Minimum file size in bytes"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """Get photos above a certain file size, sorted largest first."""
    query = select(Photo).where(Photo.file_size >= min_size)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_query)).scalar() or 0

    offset = (page - 1) * page_size
    query = query.order_by(Photo.file_size.desc()).offset(offset).limit(page_size)

    result = await session.execute(query)
    photos = result.scalars().all()

    return PhotoPage(
        items=[_photo_to_summary(p) for p in photos],
        total=total,
        page=page,
        page_size=page_size,
        has_more=offset + page_size < total,
    )
