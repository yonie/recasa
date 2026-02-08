"""Events API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_session
from backend.app.models import Photo, Event, EventPhoto
from backend.app.schemas.photo import EventSummary, PhotoPage, PhotoSummary

router = APIRouter(prefix="/api/events", tags=["events"])


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


@router.get("", response_model=list[EventSummary])
async def list_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    """List all events, sorted by start date descending."""
    result = await session.execute(
        select(Event)
        .order_by(Event.start_date.desc().nullslast())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    events = result.scalars().all()

    summaries = []
    for event in events:
        # Get cover photo (first photo in event)
        cover_result = await session.execute(
            select(Photo)
            .join(EventPhoto, EventPhoto.file_hash == Photo.file_hash)
            .where(EventPhoto.event_id == event.event_id)
            .order_by(Photo.date_taken.asc().nullslast())
            .limit(1)
        )
        cover_photo = cover_result.scalar_one_or_none()

        summaries.append(EventSummary(
            event_id=event.event_id,
            name=event.name,
            start_date=event.start_date,
            end_date=event.end_date,
            location=event.location,
            photo_count=event.photo_count,
            cover_photo=_photo_to_summary(cover_photo) if cover_photo else None,
        ))

    return summaries


@router.get("/{event_id}", response_model=EventSummary)
async def get_event(event_id: int, session: AsyncSession = Depends(get_session)):
    """Get event details."""
    event = await session.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    cover_result = await session.execute(
        select(Photo)
        .join(EventPhoto, EventPhoto.file_hash == Photo.file_hash)
        .where(EventPhoto.event_id == event.event_id)
        .order_by(Photo.date_taken.asc().nullslast())
        .limit(1)
    )
    cover_photo = cover_result.scalar_one_or_none()

    return EventSummary(
        event_id=event.event_id,
        name=event.name,
        start_date=event.start_date,
        end_date=event.end_date,
        location=event.location,
        photo_count=event.photo_count,
        cover_photo=_photo_to_summary(cover_photo) if cover_photo else None,
    )


@router.get("/{event_id}/photos", response_model=PhotoPage)
async def get_event_photos(
    event_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """Get all photos in an event."""
    event = await session.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    query = (
        select(Photo)
        .join(EventPhoto, EventPhoto.file_hash == Photo.file_hash)
        .where(EventPhoto.event_id == event_id)
    )

    count_query = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_query)).scalar() or 0

    offset = (page - 1) * page_size
    query = query.order_by(Photo.date_taken.asc().nullslast()).offset(offset).limit(page_size)

    result = await session.execute(query)
    photos = result.scalars().all()

    return PhotoPage(
        items=[_photo_to_summary(p) for p in photos],
        total=total,
        page=page,
        page_size=page_size,
        has_more=offset + page_size < total,
    )
