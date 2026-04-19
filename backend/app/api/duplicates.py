"""Duplicate and large file finder API endpoints."""

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_session
from backend.app.models import Photo, Face, Person, DuplicateGroup, DuplicateMember
from backend.app.schemas.photo import DuplicateGroupSummary, DuplicatePhotoSummary, PhotoPage, PhotoSummary
from backend.app.services.hasher import find_duplicates

router = APIRouter(prefix="/api", tags=["utilities"])

_detecting = False


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


def _photo_to_duplicate_summary(
    photo: Photo, people_names: list[str],
) -> DuplicatePhotoSummary:
    location_parts = [p for p in [photo.location_city, photo.location_country] if p]
    camera_parts = [p for p in [photo.camera_make, photo.camera_model] if p]
    return DuplicatePhotoSummary(
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
        location=", ".join(location_parts) if location_parts else None,
        camera=" ".join(camera_parts) if camera_parts else None,
        people=people_names,
    )


@router.get("/duplicates", response_model=list[DuplicateGroupSummary])
async def get_duplicates(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    """Get duplicate photo groups."""
    groups_query = (
        select(DuplicateGroup)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    groups_result = await session.execute(groups_query)
    groups = groups_result.scalars().all()

    # Collect all file_hashes we need people for
    all_member_hashes: set[str] = set()
    group_photos: dict[int, list[Photo]] = {}
    for group in groups:
        members_query = (
            select(Photo)
            .join(DuplicateMember, DuplicateMember.file_hash == Photo.file_hash)
            .where(DuplicateMember.group_id == group.group_id)
        )
        members_result = await session.execute(members_query)
        photos = members_result.scalars().all()
        group_photos[group.group_id] = photos
        all_member_hashes.update(p.file_hash for p in photos)

    # Batch-fetch people names for all photos in one query
    people_by_hash: dict[str, list[str]] = {}
    if all_member_hashes:
        people_query = (
            select(Face.file_hash, Person.name)
            .join(Person, Person.person_id == Face.person_id)
            .where(Face.file_hash.in_(all_member_hashes))
            .where(Person.name.is_not(None))
        )
        people_result = await session.execute(people_query)
        for file_hash, name in people_result:
            people_by_hash.setdefault(file_hash, []).append(name)

    result = []
    for group in groups:
        photos = group_photos[group.group_id]
        result.append(
            DuplicateGroupSummary(
                group_id=group.group_id,
                photos=[
                    _photo_to_duplicate_summary(
                        p, people_by_hash.get(p.file_hash, [])
                    )
                    for p in photos
                ],
            )
        )

    return result


@router.post("/duplicates/detect")
async def detect_duplicates(background_tasks: BackgroundTasks):
    """Trigger duplicate detection (non-blocking)."""
    global _detecting
    if _detecting:
        return {"status": "already_running"}

    async def _run():
        global _detecting
        _detecting = True
        try:
            groups = await find_duplicates()
            return groups
        finally:
            _detecting = False

    background_tasks.add_task(_run)
    return {"status": "started"}


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
