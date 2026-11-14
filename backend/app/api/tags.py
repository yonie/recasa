"""Tags API endpoints."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from backend.app.api.deps import Page, PageSize, SessionDep
from backend.app.api.responses import json_response
from backend.app.models import Photo, PhotoTag, Tag
from backend.app.queries.photos import NEWEST_FIRST, VISIBLE, photo_page, summary_select
from backend.app.queries.tags import tag_counts
from backend.app.schemas.photo import PhotoPage

router = APIRouter(prefix="/api/tags", tags=["tags"])


@router.get("")
async def list_tags(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=1000)] = 300,
    q: Annotated[str | None, Query(max_length=100)] = None,
):
    """List the most-used tags (optionally filtered by name), with photo counts.

    AI tagging produces tens of thousands of tags; returning them all made
    this endpoint a multi-MB response and the page a 74k-button DOM. Clients
    get the top `limit` by count plus the total, and search server-side.
    """
    rows = await tag_counts(session, limit=limit, name_contains=q)
    # Rows of a tag id that has no tags row sort last and only carry the
    # total; see tag_counts_query.
    items = [
        {"tag_id": r.tag_id, "name": r.name, "category": r.category, "count": r.count}
        for r in rows
        if r.known
    ]
    return json_response({"items": items, "total": rows[0].total if rows else 0})


@router.get("/{tag_id}")
async def get_tag(tag_id: int, session: SessionDep):
    """Get a single tag with its photo count."""
    tag = await session.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    count = (
        await session.execute(
            select(func.count(PhotoTag.file_hash))
            .join(Photo, Photo.file_hash == PhotoTag.file_hash)
            .where(PhotoTag.tag_id == tag_id, VISIBLE)
        )
    ).scalar() or 0

    return {"tag_id": tag.tag_id, "name": tag.name, "category": tag.category, "count": count}


@router.get("/{tag_id}/photos", response_model=PhotoPage)
async def get_tag_photos(
    tag_id: int,
    session: SessionDep,
    page: Page = 1,
    page_size: PageSize = 50,
):
    """Get all photos with a specific tag."""
    tag = await session.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    stmt = (
        summary_select()
        .join(PhotoTag, PhotoTag.file_hash == Photo.file_hash)
        .where(PhotoTag.tag_id == tag_id, VISIBLE)
    )
    return await photo_page(
        session, stmt, order_by=NEWEST_FIRST, page=page, page_size=page_size
    )
