"""A tiny in-memory library for the API-layer unit tests.

Every helper builds a fresh SQLite database from the real models, so tests
need no files, network or Docker.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.app.database import get_session
from backend.app.models import (
    Base,
    Caption,
    Event,
    EventPhoto,
    Face,
    Person,
    Photo,
    PhotoTag,
    Tag,
)


def h(n: int) -> str:
    """A valid-looking 64-hex file hash for photo number n."""
    return f"{n:064x}"


def photo(n: int, **kw: Any) -> Photo:
    fields: dict[str, Any] = {
        "file_hash": h(n),
        "file_path": f"2020/album/IMG_{n:04d}.jpg",
        "file_name": f"IMG_{n:04d}.jpg",
        "file_size": 1000 + n,
        "mime_type": "image/jpeg",
        "motion_photo": False,
        "is_favorite": False,
        "marked_for_print": False,
        "flagged_for_removal": False,
        "is_video": False,
    }
    fields.update(kw)
    return Photo(**fields)


def seed_rows() -> list[Any]:
    """Ten photos with captions, tags, people and an event.

    1-3   2020 Amsterdam, favorite 1, captions "beach" on 1 and "dog" on 2
    4     flagged for removal, tagged "beach"
    5     video, no date (file_modified only)
    6-7   2019 august, Lise and Eva together on 6, Lise alone on 7
    8     2019 december, Lise, Eva and Bob together
    9     no dates at all
    10    2021, tagged "sunny beach"
    """
    rows: list[Any] = [
        photo(1, date_taken=datetime(2020, 5, 1, 10), is_favorite=True,
              location_city="Amsterdam", location_country="NL"),
        photo(2, date_taken=datetime(2020, 5, 2, 10), location_city="Amsterdam",
              location_country="NL"),
        photo(3, date_taken=datetime(2020, 6, 1, 10), marked_for_print=True),
        photo(4, date_taken=datetime(2020, 7, 1, 10), flagged_for_removal=True),
        photo(5, file_modified=datetime(2018, 3, 3), is_video=True, duration=4.5,
              file_path="videos/clip.mp4", file_name="clip.mp4"),
        photo(6, date_taken=datetime(2019, 8, 10, 12)),
        photo(7, date_taken=datetime(2019, 8, 11, 12)),
        photo(8, date_taken=datetime(2019, 12, 24, 18), file_path="_private/x.jpg"),
        photo(9, file_path="loose.jpg", file_name="loose.jpg"),
        photo(10, date_taken=datetime(2021, 1, 1, 9), live_photo_video="2021/live.mov"),
    ]
    rows += [
        Caption(file_hash=h(1), caption="A sunny day at the beach"),
        Caption(file_hash=h(2), caption="A dog in the park"),
        Tag(tag_id=1, name="beach"),
        Tag(tag_id=2, name="sunny beach"),
        Tag(tag_id=3, name="dog"),
        PhotoTag(file_hash=h(1), tag_id=1),
        PhotoTag(file_hash=h(4), tag_id=1),
        PhotoTag(file_hash=h(10), tag_id=2),
        PhotoTag(file_hash=h(2), tag_id=3),
        PhotoTag(file_hash=h(1), tag_id=3),
        Person(person_id=1, name="Lise", photo_count=3, representative_face_id=1),
        Person(person_id=2, name="Eva", photo_count=2, representative_face_id=2),
        Person(person_id=3, name="Bob", photo_count=1),
        Person(person_id=4, name=None, photo_count=1, ignored=True),
        Face(face_id=1, file_hash=h(6), person_id=1, face_thumbnail="faces/1.webp"),
        Face(face_id=2, file_hash=h(6), person_id=2),
        Face(face_id=3, file_hash=h(7), person_id=1),
        Face(face_id=4, file_hash=h(8), person_id=1),
        Face(face_id=5, file_hash=h(8), person_id=2),
        Face(face_id=6, file_hash=h(8), person_id=3),
        Event(event_id=1, name="Summer", start_date=datetime(2020, 5, 1),
              photo_count=3, cover_file_hash=h(4)),
        EventPhoto(event_id=1, file_hash=h(1)),
        EventPhoto(event_id=1, file_hash=h(2)),
        EventPhoto(event_id=1, file_hash=h(4)),
    ]
    return rows


async def make_sessionmaker(rows: list[Any] | None = None) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        session.add_all(seed_rows() if rows is None else rows)
        await session.commit()
    return maker


def run_with_session(body: Callable[[AsyncSession], Awaitable[Any]]) -> Any:
    """Run ``body(session)`` against a freshly seeded database."""

    async def main() -> Any:
        maker = await make_sessionmaker()
        async with maker() as session:
            return await body(session)

    return asyncio.run(main())


def run_with_client(body: Callable[[httpx.AsyncClient], Awaitable[Any]]) -> Any:
    """Run ``body(client)`` against the app, its sessions on a seeded database."""
    from backend.app.main import app

    async def main() -> Any:
        maker = await make_sessionmaker()

        async def session_override():
            async with maker() as session:
                yield session

        app.dependency_overrides[get_session] = session_override
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await body(client)
        finally:
            app.dependency_overrides.pop(get_session, None)

    return asyncio.run(main())
