"""Events API endpoints."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from backend.app.api.deps import CollageGrid, Page, PageSize, SessionDep
from backend.app.api.responses import collage_response
from backend.app.models import Event, EventPhoto, Photo, PhotoHash
from backend.app.queries.photos import (
    OLDEST_FIRST,
    VISIBLE,
    photo_page,
    summary_select,
    to_summary,
)
from backend.app.schemas.photo import EventSummary, PhotoPage, PhotoSummary

router = APIRouter(prefix="/api/events", tags=["events"])


def _event_summary(event: Event, cover: PhotoSummary | None) -> EventSummary:
    return EventSummary(
        event_id=event.event_id,
        name=event.name,
        start_date=event.start_date,
        end_date=event.end_date,
        location=event.location,
        photo_count=event.photo_count,
        cover_photo=cover,
        summary=event.summary,
    )


async def _covers(session, hashes: list[str]) -> dict[str, PhotoSummary]:
    """Grid summaries of the visible photos among ``hashes``, by hash."""
    if not hashes:
        return {}
    rows = await session.execute(summary_select().where(Photo.file_hash.in_(hashes), VISIBLE))
    return {row.file_hash: to_summary(row, full=False) for row in rows}


@router.get("", response_model=list[EventSummary])
async def list_events(
    session: SessionDep,
    page: Page = 1,
    page_size: Annotated[int, Query(ge=1, le=1000)] = 50,
):
    """List all events, sorted by start date descending."""
    events = (
        (
            await session.execute(
                select(Event)
                # Same-day events keep the id order SQLite already gave them.
                .order_by(Event.start_date.desc().nullslast(), Event.event_id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    covers = await _covers(session, [e.cover_file_hash for e in events if e.cover_file_hash])
    return [
        _event_summary(e, covers.get(e.cover_file_hash) if e.cover_file_hash else None)
        for e in events
    ]


@router.get("/{event_id}", response_model=EventSummary)
async def get_event(event_id: int, session: SessionDep):
    """Get event details."""
    event = await session.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    cover = None
    if event.cover_file_hash:
        cover = (await _covers(session, [event.cover_file_hash])).get(event.cover_file_hash)
    return _event_summary(event, cover)


@router.get("/{event_id}/photos", response_model=PhotoPage)
async def get_event_photos(
    event_id: int,
    session: SessionDep,
    page: Page = 1,
    page_size: PageSize = 50,
):
    """Get all photos in an event."""
    event = await session.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    stmt = (
        summary_select()
        .join(EventPhoto, EventPhoto.file_hash == Photo.file_hash)
        .where(EventPhoto.event_id == event_id, VISIBLE)
    )
    return await photo_page(
        session, stmt, order_by=OLDEST_FIRST, page=page, page_size=page_size, full=False
    )


@router.get("/{event_id}/collage")
async def get_event_collage(
    event_id: int,
    session: SessionDep,
    grid: CollageGrid = 0,
    seed: int = 0,
):
    """Generate a square photo collage for an event."""
    event = await session.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    rows = (
        await session.execute(
            select(Photo.file_hash, PhotoHash.phash, Photo.date_taken)
            .join(EventPhoto, EventPhoto.file_hash == Photo.file_hash)
            .outerjoin(PhotoHash, PhotoHash.file_hash == Photo.file_hash)
            .where(EventPhoto.event_id == event_id, VISIBLE)
            .order_by(*OLDEST_FIRST)
        )
    ).all()
    return await collage_response(session, rows, grid, seed)
