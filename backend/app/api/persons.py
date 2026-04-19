"""Person/People API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

_IMMUTABLE_CACHE = {"Cache-Control": "public, max-age=31536000, immutable"}
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
        .where(Person.photo_count > 0, Person.ignored == False)
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


@router.get("/ignored", response_model=list[PersonSummary])
async def list_ignored_persons(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    """List all ignored persons."""
    result = await session.execute(
        select(Person)
        .where(Person.ignored == True)
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

    return FileResponse(thumb_path, media_type="image/webp", headers=_IMMUTABLE_CACHE)


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


@router.get("/groups/together")
async def list_person_groups(
    min_photos: int = Query(3, ge=2),
    page_size: int = Query(20, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
):
    """Find pairs of people who frequently appear together in the same photos.

    Uses in-memory aggregation (fast) instead of SQL self-join (slow on large face tables).
    """
    from collections import Counter
    from itertools import combinations

    # Get all (file_hash, person_id) pairs — one query, fast
    result = await session.execute(
        select(Face.file_hash, Face.person_id)
        .where(Face.person_id.is_not(None))
    )
    rows = result.all()

    # Group person_ids by photo
    photo_persons: dict[str, set[int]] = {}
    for file_hash, person_id in rows:
        photo_persons.setdefault(file_hash, set()).add(person_id)

    # Count how often each group of people appears together.
    # Use the full set of persons per photo (not just pairs) so that
    # A+B+C appearing together shows as one group, not three pairs.
    group_counts: Counter[tuple[int, ...]] = Counter()
    group_photos: dict[tuple[int, ...], str] = {}
    for file_hash, person_ids in photo_persons.items():
        if len(person_ids) < 2:
            continue
        key = tuple(sorted(person_ids))
        group_counts[key] += 1
        if key not in group_photos:
            group_photos[key] = file_hash

    # Filter and sort
    top_groups = [
        (group, count) for group, count in group_counts.most_common()
        if count >= min_photos
    ][:page_size]

    if not top_groups:
        return []

    # Fetch person details (exclude ignored)
    all_person_ids = set()
    for group, _ in top_groups:
        all_person_ids.update(group)

    persons_result = await session.execute(
        select(Person).where(Person.person_id.in_(all_person_ids), Person.ignored == False)
    )
    persons_map = {p.person_id: p for p in persons_result.scalars().all()}

    # Fetch cover photos
    cover_hashes = set(group_photos[g] for g, _ in top_groups if g in group_photos)
    photos_result = await session.execute(
        select(Photo).where(Photo.file_hash.in_(cover_hashes))
    )
    photos_map = {p.file_hash: p for p in photos_result.scalars().all()}

    def _person_info(p: Person) -> dict:
        return {
            "person_id": p.person_id,
            "name": p.name,
            "photo_count": p.photo_count,
            "face_thumbnail_url": f"/api/persons/{p.person_id}/thumbnail" if p.representative_face_id else None,
        }

    results = []
    for group, count in top_groups:
        persons_in_group = [persons_map.get(pid) for pid in group]
        # Skip if any person in the group is ignored (filtered out of map)
        if not all(persons_in_group):
            continue

        cover_hash = group_photos.get(group)
        cover_photo = photos_map.get(cover_hash) if cover_hash else None

        results.append({
            "persons": [_person_info(p) for p in persons_in_group],
            "shared_photo_count": count,
            "cover_photo": _photo_to_summary(cover_photo) if cover_photo else None,
        })

    return results


@router.get("/groups/together/{person_a_id}/{person_b_id}/photos", response_model=PhotoPage)
async def get_shared_photos(
    person_a_id: int,
    person_b_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """Get all photos where two specific people appear together."""
    return await _get_together_photos([person_a_id, person_b_id], page, page_size, session)


@router.get("/groups/together-n/photos", response_model=PhotoPage)
async def get_shared_photos_n(
    person_ids: str = Query(..., description="Comma-separated person IDs"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """Get all photos where ALL specified people appear together."""
    ids = [int(x) for x in person_ids.split(",") if x.strip().isdigit()]
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 person IDs")
    return await _get_together_photos(ids, page, page_size, session)


async def _get_together_photos(
    person_ids: list[int], page: int, page_size: int, session: AsyncSession,
) -> PhotoPage:
    """Get photos where EXACTLY the listed persons appear (no others)."""
    from sqlalchemy import intersect

    target_set = set(person_ids)

    # Step 1: photos where all listed persons appear
    sets = [
        select(Face.file_hash).where(Face.person_id == pid).distinct()
        for pid in person_ids
    ]
    together = intersect(*sets).subquery()

    # Step 2: exclude photos that have faces from OTHER person_ids
    other_faces = (
        select(Face.file_hash)
        .where(
            Face.person_id.is_not(None),
            Face.person_id.not_in(list(target_set)),
        )
        .distinct()
        .subquery()
    )

    query = select(Photo).where(
        Photo.file_hash.in_(select(together)),
        Photo.file_hash.not_in(select(other_faces)),
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


@router.get("/{person_id}/collage")
async def get_person_collage(
    person_id: int,
    grid: int = Query(0, ge=0, le=6),
    seed: int = Query(0),
    session: AsyncSession = Depends(get_session),
):
    """Generate a square photo collage for a person."""
    import asyncio
    from fastapi.responses import Response
    from backend.app.services.collage import generate_collage
    from backend.app.models import PhotoHash

    query = (
        select(Photo.file_hash, PhotoHash.phash, Photo.date_taken)
        .join(Face, Face.file_hash == Photo.file_hash)
        .outerjoin(PhotoHash, PhotoHash.file_hash == Photo.file_hash)
        .where(Face.person_id == person_id)
        .distinct(Photo.file_hash)
        .order_by(Photo.date_taken.asc().nullslast())
    )
    result = await session.execute(query)
    rows = result.all()

    if not rows:
        raise HTTPException(status_code=404, detail="No photos found")

    hashes = [r[0] for r in rows]
    phashes = [r[1] for r in rows]
    dates = [r[2] for r in rows]

    data = await asyncio.to_thread(generate_collage, hashes, phashes, grid, dates=dates, seed=seed)
    if not data:
        raise HTTPException(status_code=404, detail="Could not generate collage")

    return Response(content=data, media_type="image/jpeg")


@router.get("/groups/together/{person_a_id}/{person_b_id}/collage")
async def get_together_collage(
    person_a_id: int,
    person_b_id: int,
    grid: int = Query(0, ge=0, le=6),
    seed: int = Query(0),
    session: AsyncSession = Depends(get_session),
):
    """Generate a square photo collage for two people together."""
    return await _together_collage([person_a_id, person_b_id], grid, seed, session)


@router.get("/groups/together-n/collage")
async def get_together_collage_n(
    person_ids: str = Query(..., description="Comma-separated person IDs"),
    grid: int = Query(0, ge=0, le=6),
    seed: int = Query(0),
    session: AsyncSession = Depends(get_session),
):
    """Generate a square photo collage for N people together."""
    ids = [int(x) for x in person_ids.split(",") if x.strip().isdigit()]
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 person IDs")
    return await _together_collage(ids, grid, seed, session)


async def _together_collage(person_ids: list[int], grid: int, seed: int, session: AsyncSession):
    import asyncio
    from fastapi.responses import Response
    from backend.app.services.collage import generate_collage
    from backend.app.models import PhotoHash

    from sqlalchemy import intersect

    target_set = set(person_ids)

    # Photos where all listed persons appear
    sets = [
        select(Face.file_hash).where(Face.person_id == pid).distinct()
        for pid in person_ids
    ]
    together = intersect(*sets).subquery()

    # Exclude photos with other person_ids
    other_faces = (
        select(Face.file_hash)
        .where(
            Face.person_id.is_not(None),
            Face.person_id.not_in(list(target_set)),
        )
        .distinct()
        .subquery()
    )

    query = (
        select(Photo.file_hash, PhotoHash.phash, Photo.date_taken)
        .where(
            Photo.file_hash.in_(select(together)),
            Photo.file_hash.not_in(select(other_faces)),
        )
        .outerjoin(PhotoHash, PhotoHash.file_hash == Photo.file_hash)
        .order_by(Photo.date_taken.asc().nullslast())
    )
    result = await session.execute(query)
    rows = result.all()

    if not rows:
        raise HTTPException(status_code=404, detail="No photos found")

    hashes = [r[0] for r in rows]
    phashes = [r[1] for r in rows]
    dates = [r[2] for r in rows]

    data = await asyncio.to_thread(generate_collage, hashes, phashes, grid, dates=dates, seed=seed)
    if not data:
        raise HTTPException(status_code=404, detail="Could not generate collage")

    return Response(content=data, media_type="image/jpeg")


@router.post("/recluster")
async def recluster_persons(session: AsyncSession = Depends(get_session)):
    """Reset all person assignments and re-cluster faces from scratch.

    Preserves person names: after re-clustering, if a new cluster contains
    faces that previously belonged to a named person, the name is carried over.
    """
    from backend.app.services.face_detector import cluster_faces

    # Collect existing names before reset
    named_result = await session.execute(
        select(Person).where(Person.name.is_not(None))
    )
    named_persons = named_result.scalars().all()

    # Map face_ids to their person's name (so we can restore names after recluster)
    face_name_map: dict[int, str] = {}
    for person in named_persons:
        face_result = await session.execute(
            select(Face.face_id).where(Face.person_id == person.person_id)
        )
        for (face_id,) in face_result.all():
            face_name_map[face_id] = person.name

    # Clear all person assignments
    all_faces_result = await session.execute(
        select(Face).where(Face.person_id.is_not(None))
    )
    for face in all_faces_result.scalars().all():
        face.person_id = None
    await session.commit()

    # Delete all person records
    all_persons_result = await session.execute(select(Person))
    for person in all_persons_result.scalars().all():
        await session.delete(person)
    await session.commit()

    # Re-cluster from scratch
    new_persons = await cluster_faces()

    # Restore names: for each new person, check if any of its faces had a name
    names_restored = 0
    if face_name_map:
        persons_result = await session.execute(select(Person))
        for person in persons_result.scalars().all():
            if person.name:
                continue
            face_result = await session.execute(
                select(Face.face_id).where(Face.person_id == person.person_id)
            )
            face_ids = [fid for (fid,) in face_result.all()]
            # Find the most common name among this person's faces
            from collections import Counter
            names = [face_name_map[fid] for fid in face_ids if fid in face_name_map]
            if names:
                person.name = Counter(names).most_common(1)[0][0]
                names_restored += 1
        await session.commit()

    return {
        "status": "reclustered",
        "new_persons": new_persons,
        "names_restored": names_restored,
    }


@router.post("/{person_id}/ignore")
async def ignore_person(person_id: int, session: AsyncSession = Depends(get_session)):
    """Ignore a person — hides them from the people list and together view."""
    person = await session.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    person.ignored = True
    await session.commit()
    return {"status": "ignored", "person_id": person_id}


@router.post("/{person_id}/unignore")
async def unignore_person(person_id: int, session: AsyncSession = Depends(get_session)):
    """Un-ignore a person — restores them to the people list."""
    person = await session.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    person.ignored = False
    await session.commit()
    return {"status": "unignored", "person_id": person_id}
