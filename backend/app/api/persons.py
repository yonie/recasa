"""Person/People API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import settings
from backend.app.database import get_session
from backend.app.models import Person, Face, Photo
from backend.app.schemas.photo import (
    PersonSummary,
    PersonUpdate,
    PersonMerge,
    PhotoPage,
    PhotoSummary,
)

router = APIRouter(prefix="/api/persons", tags=["persons"])


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


@router.get("", response_model=list[PersonSummary])
async def list_persons(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """List all recognized persons, sorted by photo count descending."""
    result = await session.execute(
        select(Person)
        .where(Person.photo_count > 0)
        .order_by(Person.photo_count.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    persons = result.scalars().all()

    summaries = []
    for person in persons:
        face_thumb_url = None
        if person.representative_face_id:
            face = await session.get(Face, person.representative_face_id)
            if face and face.face_thumbnail:
                face_thumb_url = f"/api/persons/{person.person_id}/thumbnail"

        summaries.append(PersonSummary(
            person_id=person.person_id,
            name=person.name,
            photo_count=person.photo_count,
            face_thumbnail_url=face_thumb_url,
        ))

    return summaries


@router.get("/{person_id}", response_model=PersonSummary)
async def get_person(person_id: int, session: AsyncSession = Depends(get_session)):
    """Get a person's details."""
    person = await session.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    face_thumb_url = None
    if person.representative_face_id:
        face_thumb_url = f"/api/persons/{person.person_id}/thumbnail"

    return PersonSummary(
        person_id=person.person_id,
        name=person.name,
        photo_count=person.photo_count,
        face_thumbnail_url=face_thumb_url,
    )


@router.get("/{person_id}/photos", response_model=PhotoPage)
async def get_person_photos(
    person_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """Get all photos containing a specific person."""
    person = await session.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    # Get unique photo hashes for this person
    query = (
        select(Photo)
        .join(Face, Face.file_hash == Photo.file_hash)
        .where(Face.person_id == person_id)
        .distinct()
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


@router.get("/{person_id}/thumbnail")
async def get_person_thumbnail(person_id: int, session: AsyncSession = Depends(get_session)):
    """Serve the representative face thumbnail for a person."""
    person = await session.get(Person, person_id)
    if not person or not person.representative_face_id:
        raise HTTPException(status_code=404, detail="Person not found")

    face = await session.get(Face, person.representative_face_id)
    if not face or not face.face_thumbnail:
        raise HTTPException(status_code=404, detail="Face thumbnail not found")

    thumb_path = settings.data_dir / face.face_thumbnail
    if not thumb_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail file not found")

    return FileResponse(thumb_path, media_type="image/webp")


@router.put("/{person_id}", response_model=PersonSummary)
async def update_person(
    person_id: int,
    update: PersonUpdate,
    session: AsyncSession = Depends(get_session),
):
    """Update a person's name."""
    person = await session.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    person.name = update.name
    await session.commit()

    face_thumb_url = None
    if person.representative_face_id:
        face_thumb_url = f"/api/persons/{person.person_id}/thumbnail"

    return PersonSummary(
        person_id=person.person_id,
        name=person.name,
        photo_count=person.photo_count,
        face_thumbnail_url=face_thumb_url,
    )


@router.post("/merge")
async def merge_persons(
    merge: PersonMerge,
    session: AsyncSession = Depends(get_session),
):
    """Merge two persons: move all faces from source to target, then delete source."""
    source = await session.get(Person, merge.source_id)
    target = await session.get(Person, merge.target_id)

    if not source or not target:
        raise HTTPException(status_code=404, detail="Person not found")

    if merge.source_id == merge.target_id:
        raise HTTPException(status_code=400, detail="Cannot merge a person with themselves")

    # Move all faces from source to target
    result = await session.execute(
        select(Face).where(Face.person_id == merge.source_id)
    )
    faces = result.scalars().all()

    for face in faces:
        face.person_id = merge.target_id

    # Update target photo count
    face_count = await session.execute(
        select(func.count(func.distinct(Face.file_hash)))
        .where(Face.person_id == merge.target_id)
    )
    target.photo_count = face_count.scalar() or 0

    # Delete source person
    await session.delete(source)
    await session.commit()

    return {
        "status": "merged",
        "target_id": merge.target_id,
        "faces_moved": len(faces),
    }
