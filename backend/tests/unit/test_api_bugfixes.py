"""Regression tests for API-layer bugs that changed responses when fixed."""

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

from api_fixtures import h, run_with_client, seed_rows  # noqa: E402

from backend.app.models import (  # noqa: E402
    DuplicateGroup,
    DuplicateMember,
    EventPhoto,
    Face,
    Photo,
    PhotoTag,
)


def _seeded(**changes: dict[str, Any]) -> list[Any]:
    """The standard seed with attribute changes per photo number ("p5": {...})."""
    rows = seed_rows()
    for row in rows:
        if isinstance(row, Photo):
            for attr, value in changes.get(f"p{int(row.file_hash, 16)}", {}).items():
                setattr(row, attr, value)
    return rows


# --- every grid returns the full tile ---------------------------------------


def _video_everywhere_rows() -> list[Any]:
    """Video 5 (and print-marked 7) put on every kind of grid."""
    rows = _seeded(
        p5={"location_city": "Amsterdam", "location_country": "NL", "file_size": 50_000_000},
        p7={"marked_for_print": True, "file_size": 60_000_000},
    )
    rows += [
        Face(face_id=7, file_hash=h(5), person_id=1),
        Face(face_id=8, file_hash=h(5), person_id=2),
        PhotoTag(file_hash=h(5), tag_id=3),
        EventPhoto(event_id=1, file_hash=h(5)),
        DuplicateGroup(group_id=1),
        DuplicateMember(group_id=1, file_hash=h(5)),
        DuplicateMember(group_id=1, file_hash=h(7)),
    ]
    return rows


GRID_FIELDS = ("is_video", "duration", "marked_for_print", "flagged_for_removal")


def test_every_grid_returns_the_same_tile_as_the_library():
    async def body(client):
        library = (await client.get("/api/photos", params={"page_size": 200})).json()
        grids = {
            url: (await client.get(url)).json()
            for url in (
                "/api/persons/1/photos",
                "/api/tags/3/photos",
                "/api/events/1/photos",
                "/api/locations/photos?city=Amsterdam",
                "/api/directories/videos",
                "/api/large-files",
                "/api/persons/groups/together/1/2/photos",
            )
        }
        duplicates = (await client.get("/api/duplicates")).json()
        together = (
            await client.get("/api/persons/groups/together", params={"min_photos": 2})
        ).json()
        return library, grids, duplicates, together

    library, grids, duplicates, together = run_with_client(body, _video_everywhere_rows())
    by_hash = {p["file_hash"]: p for p in library["items"]}
    assert by_hash[h(5)]["is_video"] is True and by_hash[h(5)]["duration"] == 4.5

    for url, page in grids.items():
        hashes = [p["file_hash"] for p in page["items"]]
        assert h(5) in hashes, url
        for item in page["items"]:
            assert item == by_hash[item["file_hash"]], url

    members = {p["file_hash"]: p for p in duplicates[0]["photos"]}
    for file_hash, member in members.items():
        for field in GRID_FIELDS:
            assert member[field] == by_hash[file_hash][field]
    assert members[h(5)]["is_video"] is True
    assert members[h(7)]["marked_for_print"] is True

    # Lise and Eva share photos 5 and 6 now, so they form a Together tile.
    cover = together[0]["cover_photo"]
    assert cover == by_hash[cover["file_hash"]]


def test_event_cover_is_a_full_tile():
    async def body(client):
        return (await client.get("/api/events/1")).json()

    event = run_with_client(body, _seeded(p4={"flagged_for_removal": False, "is_video": True}))
    assert event["cover_photo"]["file_hash"] == h(4)
    assert event["cover_photo"]["is_video"] is True
