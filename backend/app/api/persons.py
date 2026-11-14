"""Person/People API endpoints."""

import re
from collections import Counter
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import Select, delete, func, intersect, select, update

from backend.app.api.deps import CollageGrid, Page, PageSize, SessionDep
from backend.app.api.files import REVALIDATE, contained_path, file_response
from backend.app.api.responses import collage_response
from backend.app.config import settings
from backend.app.models import Face, HiddenPersonGroup, Person, Photo, PhotoHash
from backend.app.models.face import group_key_from_ids as _group_key
from backend.app.queries.photos import (
    NEWEST_FIRST,
    OLDEST_FIRST,
    VISIBLE,
    photo_page,
    summary_select,
    to_summary,
)
from backend.app.schemas.photo import PersonMerge, PersonSummary, PersonUpdate, PhotoPage

router = APIRouter(prefix="/api/persons", tags=["persons"])

PersonIds = Annotated[str, Query(description="Comma-separated person IDs")]

# A together group is a handful of people. The bound keeps a crafted list
# from turning into an INTERSECT of thousands of subqueries.
MAX_GROUP_SIZE = 50
# ASCII digits only, at most 18 so the value fits an SQLite INTEGER.
_PERSON_ID = re.compile(r"[0-9]{1,18}")

# Most photos first. Thousands of people share a count, and SQLite returned
# those in id order; the tiebreak makes that explicit so pages stay stable.
_MOST_PHOTOS_FIRST = (Person.photo_count.desc(), Person.person_id)


def _thumbnail_url(person: Person) -> str | None:
    """Face thumbnail URL for a person that has a representative face."""
    if person.representative_face_id:
        return f"/api/persons/{person.person_id}/thumbnail"
    return None


def _person_info(p: Person) -> dict:
    return {
        "person_id": p.person_id,
        "name": p.name,
        "photo_count": p.photo_count,
        "face_thumbnail_url": _thumbnail_url(p),
    }


def _summary(person: Person, face_thumbnail_url: str | None) -> PersonSummary:
    return PersonSummary(
        person_id=person.person_id,
        name=person.name,
        photo_count=person.photo_count,
        face_thumbnail_url=face_thumbnail_url,
    )


def _parse_person_ids(person_ids: str) -> list[int]:
    """The ids in a comma-separated list; anything that is not one is skipped."""
    ids = [int(token) for x in person_ids.split(",") if _PERSON_ID.fullmatch(token := x.strip())]
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 person IDs")
    if len(ids) > MAX_GROUP_SIZE:
        raise HTTPException(status_code=400, detail="Too many person IDs")
    return ids


async def _list_summaries(session, stmt: Select[Any]) -> list[PersonSummary]:
    """Person summaries for a listing, linking the thumbnail only where the
    representative face actually has a crop on record."""
    persons = (await session.execute(stmt)).scalars().all()
    face_ids = {p.representative_face_id for p in persons if p.representative_face_id}
    with_crop: set[int] = set()
    if face_ids:
        with_crop = set(
            (
                await session.execute(
                    select(Face.face_id).where(
                        Face.face_id.in_(face_ids),
                        Face.face_thumbnail.is_not(None),
                        Face.face_thumbnail != "",
                    )
                )
            ).scalars()
        )
    return [
        _summary(p, _thumbnail_url(p) if p.representative_face_id in with_crop else None)
        for p in persons
    ]


@router.get("", response_model=list[PersonSummary])
async def list_persons(
    session: SessionDep,
    page: Page = 1,
    page_size: PageSize = 50,
):
    """List all recognized persons, sorted by photo count descending."""
    return await _list_summaries(
        session,
        select(Person)
        .where(Person.photo_count > 0, Person.ignored == False)  # noqa: E712
        .order_by(*_MOST_PHOTOS_FIRST)
        .offset((page - 1) * page_size)
        .limit(page_size),
    )


@router.get("/ignored", response_model=list[PersonSummary])
async def list_ignored_persons(
    session: SessionDep,
    page: Page = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 100,
):
    """List all ignored persons."""
    return await _list_summaries(
        session,
        select(Person)
        .where(Person.ignored == True)  # noqa: E712
        .order_by(*_MOST_PHOTOS_FIRST)
        .offset((page - 1) * page_size)
        .limit(page_size),
    )


@router.get("/{person_id}", response_model=PersonSummary)
async def get_person(person_id: int, session: SessionDep):
    """Get a person's details."""
    person = await session.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    return _summary(person, _thumbnail_url(person))


@router.get("/{person_id}/photos", response_model=PhotoPage)
async def get_person_photos(
    person_id: int,
    session: SessionDep,
    page: Page = 1,
    page_size: PageSize = 50,
):
    """Get all photos containing a specific person."""
    person = await session.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    stmt = (
        summary_select()
        .join(Face, Face.file_hash == Photo.file_hash)
        .where(Face.person_id == person_id, VISIBLE)
        .distinct()
    )
    return await photo_page(
        session, stmt, order_by=NEWEST_FIRST, page=page, page_size=page_size, full=False
    )


@router.get("/{person_id}/thumbnail")
async def get_person_thumbnail(person_id: int, request: Request, session: SessionDep):
    """Serve the representative face thumbnail for a person.

    Revalidated rather than cached for good: the URL names a person, and a
    merge, a recluster or a new representative face changes the picture
    behind it.
    """
    person = await session.get(Person, person_id)
    if not person or not person.representative_face_id:
        raise HTTPException(status_code=404, detail="Person not found")

    face = await session.get(Face, person.representative_face_id)
    if not face or not face.face_thumbnail:
        raise HTTPException(status_code=404, detail="Face thumbnail not found")

    thumb_path = contained_path(settings.data_dir, face.face_thumbnail)
    if thumb_path is None or not thumb_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail file not found")

    return file_response(request, thumb_path, "image/webp", cache_control=REVALIDATE)


@router.put("/{person_id}", response_model=PersonSummary)
async def update_person(person_id: int, update: PersonUpdate, session: SessionDep):
    """Update a person's name."""
    person = await session.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    person.name = update.name
    await session.commit()
    return _summary(person, _thumbnail_url(person))


@router.post("/merge")
async def merge_persons(merge: PersonMerge, session: SessionDep):
    """Merge two persons: move all faces from source to target, then delete source."""
    source = await session.get(Person, merge.source_id)
    target = await session.get(Person, merge.target_id)

    if not source or not target:
        raise HTTPException(status_code=404, detail="Person not found")

    if merge.source_id == merge.target_id:
        raise HTTPException(status_code=400, detail="Cannot merge a person with themselves")

    faces = (
        (await session.execute(select(Face).where(Face.person_id == merge.source_id)))
        .scalars()
        .all()
    )
    for face in faces:
        face.person_id = merge.target_id

    # Autoflush puts the moved faces in the count.
    target.photo_count = (
        await session.execute(
            select(func.count(func.distinct(Face.file_hash))).where(
                Face.person_id == merge.target_id
            )
        )
    ).scalar() or 0

    await session.delete(source)
    await session.commit()

    return {
        "status": "merged",
        "target_id": merge.target_id,
        "faces_moved": len(faces),
    }


@router.get("/groups/together")
async def list_person_groups(
    session: SessionDep,
    min_photos: Annotated[int, Query(ge=2)] = 3,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
):
    """Find pairs of people who frequently appear together in the same photos.

    Uses in-memory aggregation (fast) instead of SQL self-join (slow on large face tables).
    """
    # In face order: the first photo seen becomes a group's cover and the
    # first group seen wins a tie in the ranking.
    rows = await session.execute(
        select(Face.file_hash, Face.person_id)
        .where(Face.person_id.is_not(None))
        .order_by(Face.face_id)
    )

    # Group person_ids by photo
    photo_persons: dict[str, set[int]] = {}
    for file_hash, person_id in rows:
        photo_persons.setdefault(file_hash, set()).add(person_id)

    # Count how often each group of people appears together, using the full
    # set of persons per photo (not just pairs) so that A+B+C together shows
    # as one group, not three pairs.
    group_counts: Counter[tuple[int, ...]] = Counter()
    group_photos: dict[tuple[int, ...], str] = {}
    for file_hash, person_ids in photo_persons.items():
        if len(person_ids) < 2:
            continue
        key = tuple(sorted(person_ids))
        group_counts[key] += 1
        group_photos.setdefault(key, file_hash)

    # Drop tiles the user hid from the Together section before slicing to
    # page_size, so hiding tiles makes room for the next-best groups.
    hidden_keys = set((await session.execute(select(HiddenPersonGroup.group_key))).scalars())

    top_groups = [
        (group, count)
        for group, count in group_counts.most_common()
        if count >= min_photos and _group_key(group) not in hidden_keys
    ][:page_size]

    if not top_groups:
        return []

    all_person_ids = {pid for group, _ in top_groups for pid in group}
    persons_map = {
        p.person_id: p
        for p in (
            await session.execute(
                select(Person).where(
                    Person.person_id.in_(all_person_ids),
                    Person.ignored == False,  # noqa: E712
                )
            )
        ).scalars()
    }

    cover_hashes = {group_photos[g] for g, _ in top_groups}
    photos_map = {
        row.file_hash: row
        for row in await session.execute(
            summary_select().where(Photo.file_hash.in_(cover_hashes), VISIBLE)
        )
    }

    results = []
    for group, count in top_groups:
        persons_in_group = [persons_map.get(pid) for pid in group]
        # Skip if any person in the group is ignored (filtered out of map)
        if not all(persons_in_group):
            continue
        cover = photos_map.get(group_photos[group])
        results.append(
            {
                "persons": [_person_info(p) for p in persons_in_group],
                "shared_photo_count": count,
                "cover_photo": to_summary(cover, full=False) if cover else None,
            }
        )

    return results


class PersonIdsRequest(BaseModel):
    person_ids: Annotated[
        list[Annotated[int, Field(ge=0, le=2**63 - 1)]], Field(max_length=MAX_GROUP_SIZE)
    ]


@router.get("/groups/hidden")
async def list_hidden_person_groups(session: SessionDep):
    """Together-section tiles the user hid, for the restore row on the people page."""
    keys = await session.execute(
        select(HiddenPersonGroup.group_key).order_by(HiddenPersonGroup.group_key)
    )

    parsed: list[tuple[str, list[int]]] = []
    all_ids: set[int] = set()
    for key in keys.scalars():
        try:
            ids = [int(x) for x in key.split(",") if x]
        except ValueError:
            continue  # not a key this app wrote; skip rather than 500
        parsed.append((key, ids))
        all_ids.update(ids)

    if not parsed:
        return []

    # Person details for the restore chips. A person may be gone after a
    # recluster, in which case it is simply left out of the chip.
    persons_map = {
        p.person_id: p
        for p in (
            await session.execute(
                select(Person).where(Person.person_id.in_(all_ids), Person.ignored == False)  # noqa: E712
            )
        ).scalars()
    }

    return [
        {
            "group_key": key,
            "persons": [_person_info(persons_map[pid]) for pid in ids if pid in persons_map],
        }
        for key, ids in parsed
    ]


@router.post("/groups/hide")
async def hide_person_group(body: PersonIdsRequest, session: SessionDep):
    """Hide one Together tile (the people that appear together in photos).

    This only removes the tile from the Together section; the people
    themselves stay on the people page and in their photos.
    """
    if len(body.person_ids) < 2:
        raise HTTPException(status_code=400, detail="A group needs at least two person_ids")
    key = _group_key(body.person_ids)
    if await session.get(HiddenPersonGroup, key) is None:
        session.add(HiddenPersonGroup(group_key=key))
        await session.commit()
    return {"status": "hidden", "group_key": key}


@router.post("/groups/unhide")
async def unhide_person_group(body: PersonIdsRequest, session: SessionDep):
    """Restore a hidden Together tile."""
    key = _group_key(body.person_ids)
    row = await session.get(HiddenPersonGroup, key)
    if row is not None:
        await session.delete(row)
        await session.commit()
    return {"status": "unhidden", "group_key": key}


def _together_conditions(person_ids: list[int]) -> list[Any]:
    """Photos where all the listed persons appear and no other person does.

    "No other person" is checked per candidate photo through the faces
    file_hash index. The previous NOT IN built the set of every photo with
    any other recognised face (most of the library) on each request, which
    was nearly all of its ~0.4 s.
    """
    together = intersect(
        *(select(Face.file_hash).where(Face.person_id == pid).distinct() for pid in person_ids)
    ).subquery()
    someone_else = (
        select(Face.face_id)
        .where(
            Face.file_hash == Photo.file_hash,
            Face.person_id.is_not(None),
            Face.person_id.not_in(list(set(person_ids))),
        )
        .exists()
    )
    return [Photo.file_hash.in_(select(together)), ~someone_else, VISIBLE]


@router.get("/groups/together/{person_a_id}/{person_b_id}/photos", response_model=PhotoPage)
async def get_shared_photos(
    person_a_id: int,
    person_b_id: int,
    session: SessionDep,
    page: Page = 1,
    page_size: PageSize = 50,
):
    """Get all photos where two specific people appear together."""
    return await _get_together_photos([person_a_id, person_b_id], page, page_size, session)


@router.get("/groups/together-n/photos", response_model=PhotoPage)
async def get_shared_photos_n(
    person_ids: PersonIds,
    session: SessionDep,
    page: Page = 1,
    page_size: PageSize = 50,
):
    """Get all photos where ALL specified people appear together."""
    return await _get_together_photos(_parse_person_ids(person_ids), page, page_size, session)


async def _get_together_photos(
    person_ids: list[int], page: int, page_size: int, session
) -> PhotoPage:
    """Get photos where EXACTLY the listed persons appear (no others)."""
    stmt = summary_select().where(*_together_conditions(person_ids))
    return await photo_page(
        session, stmt, order_by=NEWEST_FIRST, page=page, page_size=page_size, full=False
    )


@router.get("/{person_id}/collage")
async def get_person_collage(
    person_id: int,
    request: Request,
    session: SessionDep,
    grid: CollageGrid = 0,
    seed: int = 0,
):
    """Generate a square photo collage for a person."""
    rows = (
        await session.execute(
            select(Photo.file_hash, PhotoHash.phash, Photo.date_taken)
            .join(Face, Face.file_hash == Photo.file_hash)
            .outerjoin(PhotoHash, PhotoHash.file_hash == Photo.file_hash)
            .where(Face.person_id == person_id, VISIBLE)
            .distinct()
            .order_by(*OLDEST_FIRST)
        )
    ).all()
    return await collage_response(request, session, rows, grid, seed)


@router.get("/groups/together/{person_a_id}/{person_b_id}/collage")
async def get_together_collage(
    person_a_id: int,
    person_b_id: int,
    request: Request,
    session: SessionDep,
    grid: CollageGrid = 0,
    seed: int = 0,
):
    """Generate a square photo collage for two people together."""
    return await _together_collage(request, [person_a_id, person_b_id], grid, seed, session)


@router.get("/groups/together-n/collage")
async def get_together_collage_n(
    person_ids: PersonIds,
    request: Request,
    session: SessionDep,
    grid: CollageGrid = 0,
    seed: int = 0,
):
    """Generate a square photo collage for N people together."""
    return await _together_collage(request, _parse_person_ids(person_ids), grid, seed, session)


async def _together_collage(
    request: Request, person_ids: list[int], grid: int, seed: int, session
):
    rows = (
        await session.execute(
            select(Photo.file_hash, PhotoHash.phash, Photo.date_taken)
            .where(*_together_conditions(person_ids))
            .outerjoin(PhotoHash, PhotoHash.file_hash == Photo.file_hash)
            .order_by(*OLDEST_FIRST)
        )
    ).all()
    return await collage_response(request, session, rows, grid, seed)


@router.post("/recluster")
async def recluster_persons(session: SessionDep):
    """Reset all person assignments and re-cluster faces from scratch.

    Preserves person names: after re-clustering, if a new cluster contains
    faces that previously belonged to a named person, the name is carried over.
    """
    from backend.app.services.face_detector import cluster_faces

    # Map face_ids to their person's name (so we can restore names after recluster)
    face_name_map: dict[int, str | None] = dict(
        (
            await session.execute(
                select(Face.face_id, Person.name)
                .join(Person, Person.person_id == Face.person_id)
                .where(Person.name.is_not(None))
            )
        ).tuples()
    )

    # Clear all person assignments, then every person record. Bulk statements:
    # deleting persons one ORM object at a time lazy-loaded each one's faces
    # first, tens of thousands of queries for an identical end state.
    await session.execute(
        update(Face).where(Face.person_id.is_not(None)).values(person_id=None)
    )
    await session.commit()
    await session.execute(delete(Person))
    await session.commit()

    # Re-cluster from scratch
    new_persons = await cluster_faces()

    # Restore names: each new person gets the most common old name among its faces
    names_restored = 0
    if face_name_map:
        faces_by_person: dict[int, list[int]] = {}
        for face_id, person_id in await session.execute(
            select(Face.face_id, Face.person_id)
            .where(Face.person_id.is_not(None))
            .order_by(Face.face_id)
        ):
            faces_by_person.setdefault(person_id, []).append(face_id)
        for person in (await session.execute(select(Person))).scalars():
            if person.name:
                continue
            names = [
                face_name_map[fid]
                for fid in faces_by_person.get(person.person_id, [])
                if fid in face_name_map
            ]
            if names:
                person.name = Counter(names).most_common(1)[0][0]
                names_restored += 1
        await session.commit()

    return {
        "status": "reclustered",
        "new_persons": new_persons,
        "names_restored": names_restored,
    }


async def _set_ignored(session, person_id: int, ignored: bool) -> None:
    person = await session.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    person.ignored = ignored
    await session.commit()


@router.post("/{person_id}/ignore")
async def ignore_person(person_id: int, session: SessionDep):
    """Ignore a person: hides them from the people list and together view."""
    await _set_ignored(session, person_id, True)
    return {"status": "ignored", "person_id": person_id}


@router.post("/{person_id}/unignore")
async def unignore_person(person_id: int, session: SessionDep):
    """Un-ignore a person: restores them to the people list."""
    await _set_ignored(session, person_id, False)
    return {"status": "unignored", "person_id": person_id}
