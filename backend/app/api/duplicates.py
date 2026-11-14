"""Duplicate and large file finder API endpoints."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Query
from sqlalchemy import select

from backend.app.api.deps import Page, PageSize, SessionDep
from backend.app.models import DuplicateGroup, DuplicateMember, Face, Person, Photo
from backend.app.queries.photos import (
    SUMMARY_COLUMNS,
    VISIBLE,
    photo_page,
    summary_select,
    to_summary,
)
from backend.app.schemas.photo import DuplicateGroupSummary, DuplicatePhotoSummary, PhotoPage
from backend.app.services.hasher import find_duplicates

router = APIRouter(prefix="/api", tags=["utilities"])

_detecting = False


# Grid-tile columns plus what the comparison view shows besides
_MEMBER_COLUMNS = (
    *SUMMARY_COLUMNS,
    Photo.location_city,
    Photo.location_country,
    Photo.camera_make,
    Photo.camera_model,
)


def _photo_to_duplicate_summary(photo, people_names: list[str]) -> DuplicatePhotoSummary:
    location_parts = [p for p in [photo.location_city, photo.location_country] if p]
    camera_parts = [p for p in [photo.camera_make, photo.camera_model] if p]
    return DuplicatePhotoSummary(
        **to_summary(photo).model_dump(exclude_unset=True),
        location=", ".join(location_parts) if location_parts else None,
        camera=" ".join(camera_parts) if camera_parts else None,
        people=people_names,
    )


@router.get("/duplicates", response_model=list[DuplicateGroupSummary])
async def get_duplicates(
    session: SessionDep,
    page: Page = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """Get duplicate photo groups."""
    group_ids = (
        (
            await session.execute(
                select(DuplicateGroup.group_id).offset((page - 1) * page_size).limit(page_size)
            )
        )
        .scalars()
        .all()
    )

    # All members of the page's groups in one query, each group's members in
    # hash order as the per-group lookups returned them.
    group_photos: dict[int, list] = {gid: [] for gid in group_ids}
    if group_ids:
        members = await session.execute(
            select(*_MEMBER_COLUMNS, DuplicateMember.group_id)
            .join(DuplicateMember, DuplicateMember.file_hash == Photo.file_hash)
            .where(DuplicateMember.group_id.in_(group_ids), VISIBLE)
            .order_by(DuplicateMember.group_id, DuplicateMember.file_hash)
        )
        for row in members:
            group_photos[row.group_id].append(row)

    # People names for every member photo in one query
    member_hashes = {p.file_hash for photos in group_photos.values() for p in photos}
    people_by_hash: dict[str, list[str]] = {}
    if member_hashes:
        people = await session.execute(
            select(Face.file_hash, Person.name)
            .join(Person, Person.person_id == Face.person_id)
            .where(Face.file_hash.in_(member_hashes))
            .where(Person.name.is_not(None))
            .order_by(Face.face_id)
        )
        for file_hash, name in people:
            people_by_hash.setdefault(file_hash, []).append(name)

    return [
        DuplicateGroupSummary(
            group_id=gid,
            photos=[
                _photo_to_duplicate_summary(p, people_by_hash.get(p.file_hash, []))
                for p in photos
            ],
        )
        for gid, photos in group_photos.items()
        # A group left with one photo after hiding flagged ones has no duplicates.
        if len(photos) >= 2
    ]


@router.post("/duplicates/detect")
async def detect_duplicates(background_tasks: BackgroundTasks):
    """Trigger duplicate detection (non-blocking)."""
    if _detecting:
        return {"status": "already_running"}

    async def _run():
        global _detecting
        _detecting = True
        try:
            await find_duplicates()
        finally:
            _detecting = False

    background_tasks.add_task(_run)
    return {"status": "started"}


@router.get("/large-files", response_model=PhotoPage)
async def get_large_files(
    session: SessionDep,
    min_size: Annotated[
        int, Query(ge=0, description="Minimum file size in bytes")
    ] = 10_000_000,
    page: Page = 1,
    page_size: PageSize = 50,
):
    """Get photos above a certain file size, sorted largest first."""
    stmt = summary_select().where(Photo.file_size >= min_size, VISIBLE)
    return await photo_page(
        session,
        stmt,
        order_by=(Photo.file_size.desc(),),
        page=page,
        page_size=page_size,
    )
