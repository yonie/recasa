"""Regression tests for API-layer bugs that changed responses when fixed."""

import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent))

from api_fixtures import h, photo, run_with_client, seed_rows  # noqa: E402

from backend.app.models import (  # noqa: E402
    DuplicateGroup,
    DuplicateMember,
    EventPhoto,
    Face,
    HiddenPersonGroup,
    Person,
    Photo,
    PhotoTag,
    Tag,
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


# --- folders starting with "_" ----------------------------------------------


def test_underscore_folders_are_listed_and_browsable():
    async def body(client):
        tree = (await client.get("/api/directories")).json()
        grid = (await client.get("/api/directories/_private")).json()
        return tree, grid

    tree, grid = run_with_client(body)
    assert [n["name"] for n in tree] == ["2020", "_private", "videos"]
    assert tree[1]["photo_count"] == 1 and tree[1]["path"] == "_private"
    assert [p["file_hash"] for p in grid["items"]] == [h(8)]


# --- folder grids match the folder exactly -----------------------------------


def test_directory_photos_match_the_exact_folder():
    rows = _seeded(
        p1={"file_path": "2026/2026_09/a.jpg"},
        p2={"file_path": "2026/2026-09/b.jpg"},  # "_" used to match "-"
        p3={"file_path": "2026/2026_09x/c.jpg"},  # sibling sharing the prefix
        p6={"file_path": "2026/2026_09/deeper/d.jpg"},
        p7={"file_path": "2026/2026_09.jpg"},  # a file, not the folder
        p10={"file_path": "Trips/x.jpg"},
    )
    rows.append(Photo(file_hash=h(11), file_path="trips/y.jpg", file_name="y.jpg",
                      file_size=1, motion_photo=False))

    async def body(client):
        async def grid(path):
            page = (await client.get(f"/api/directories/{quote(path)}")).json()
            return sorted(int(p["file_hash"], 16) for p in page["items"])

        return {p: await grid(p) for p in ("2026/2026_09", "2026/2026%09", "Trips", "trips")}

    found = run_with_client(body, rows)
    assert found == {"2026/2026_09": [1, 6], "2026/2026%09": [], "Trips": [10], "trips": [11]}


# --- search takes "_" and "%" literally --------------------------------------


def test_search_and_tag_filter_take_wildcards_literally():
    rows = _seeded(
        p1={"file_name": "IMG_0001.jpg"},
        p2={"file_name": "IMG-0002.jpg", "file_path": "2020/album/IMG-0002.jpg"},
        p3={"file_name": "100%.jpg", "file_path": "2020/album/100%.jpg"},
        p6={"file_name": "1000.jpg", "file_path": "2020/album/1000.jpg"},
        p7={"file_name": "back\\slash.jpg", "file_path": "x/back\\slash.jpg"},
    )
    rows.append(PhotoTag(file_hash=h(7), tag_id=4))
    rows.append(Tag(tag_id=4, name="snow_man"))
    rows.append(Tag(tag_id=5, name="snowyman"))
    rows.append(PhotoTag(file_hash=h(6), tag_id=5))

    async def body(client):
        async def search(q):
            page = (await client.get("/api/photos", params={"search": q})).json()
            return sorted(int(p["file_hash"], 16) for p in page["items"])

        async def tags(q):
            data = (await client.get("/api/tags", params={"q": q})).json()
            return [t["name"] for t in data["items"]]

        return (
            {q: await search(q) for q in ("IMG_", "img_", "100%", "0%", "back\\slash")},
            {q: await tags(q) for q in ("snow_", "_", "SNOW")},
        )

    photos, tags = run_with_client(body, rows)
    assert photos == {
        "IMG_": [1, 8, 10],  # IMG-0002 no longer matches
        "img_": [1, 8, 10],  # still case-insensitive
        "100%": [3],
        "0%": [3],
        "back\\slash": [7],
    }
    assert tags == {"snow_": ["snow_man"], "_": ["snow_man"], "SNOW": ["snow_man", "snowyman"]}


# --- a person's thumbnail URL only when the crop exists ----------------------


def test_person_thumbnail_url_needs_a_crop_everywhere():
    rows = seed_rows()
    # Lise and Eva together on a second photo, so they form a Together tile;
    # Bob's representative face points at a face that does not exist.
    rows += [
        Face(face_id=9, file_hash=h(7), person_id=2),
        HiddenPersonGroup(group_key="1,3"),
    ]
    for row in rows:
        if isinstance(row, Person) and row.person_id == 3:
            row.representative_face_id = 999

    async def body(client):
        listing = (await client.get("/api/persons")).json()
        single = {pid: (await client.get(f"/api/persons/{pid}")).json() for pid in (1, 2, 3)}
        renamed = (await client.put("/api/persons/2", json={"name": "Eva B"})).json()
        together = (
            await client.get("/api/persons/groups/together", params={"min_photos": 2})
        ).json()
        hidden = (await client.get("/api/persons/groups/hidden")).json()
        return listing, single, renamed, together, hidden

    listing, single, renamed, together, hidden = run_with_client(body, rows)
    expected = {1: "/api/persons/1/thumbnail", 2: None, 3: None}
    assert {p["person_id"]: p["face_thumbnail_url"] for p in listing} == expected
    assert {pid: p["face_thumbnail_url"] for pid, p in single.items()} == expected
    assert renamed["name"] == "Eva B" and renamed["face_thumbnail_url"] is None
    assert [(p["person_id"], p["face_thumbnail_url"]) for p in together[0]["persons"]] == [
        (1, expected[1]),
        (2, None),
    ]
    assert [(p["person_id"], p["face_thumbnail_url"]) for p in hidden[0]["persons"]] == [
        (1, expected[1]),
        (3, None),
    ]


# --- ties sort by file_hash ---------------------------------------------------


_SHUFFLED = [7, 2, 11, 5, 9, 1, 12, 4, 10, 3, 8, 6]
_UNDATED = {4, 9}


def _tied_rows() -> list[Any]:
    """Twelve photos inserted out of hash order: ten share one timestamp and
    one size, two have no date. All carry tag 1 and Lise's face."""
    rows: list[Any] = [Tag(tag_id=1, name="tie"), Person(person_id=1, name="Lise", photo_count=12)]
    for n in _SHUFFLED:
        rows.append(
            photo(
                n,
                date_taken=None if n in _UNDATED else datetime(2020, 1, 1, 12),
                file_modified=datetime(2020, 1, 1, 12),
                file_size=20_000_000,
                file_path=f"2020/tie/{n}.jpg",
            )
        )
        rows += [PhotoTag(file_hash=h(n), tag_id=1), Face(file_hash=h(n), person_id=1)]
    return rows


def _paged(client, url: str, **params: Any):
    async def pages() -> list[int]:
        found: list[int] = []
        for page in (1, 2, 3, 4):
            data = (
                await client.get(url, params={**params, "page": page, "page_size": 4})
            ).json()
            found += [int(p["file_hash"], 16) for p in data["items"]]
        return found

    return pages()


def test_paged_grids_break_ties_by_hash():
    dated = sorted(set(_SHUFFLED) - _UNDATED)
    newest = sorted(dated, reverse=True) + sorted(_UNDATED, reverse=True)

    async def body(client):
        return {
            "desc": await _paged(client, "/api/photos"),
            "asc": await _paged(client, "/api/photos", order="asc"),
            "size": await _paged(client, "/api/photos", sort="file_size", order="desc"),
            "person": await _paged(client, "/api/persons/1/photos"),
            "tag": await _paged(client, "/api/tags/1/photos"),
            "folder": await _paged(client, "/api/directories/2020"),
            "large": await _paged(client, "/api/large-files"),
            "search": await _paged(client, "/api/photos", search="jpg"),
        }

    found = run_with_client(body, _tied_rows())
    assert found["desc"] == newest
    # Oldest first is the same order reversed: undated first, then by hash.
    assert found["asc"] == list(reversed(newest))
    assert found["size"] == sorted(_SHUFFLED, reverse=True)
    assert found["large"] == sorted(_SHUFFLED, reverse=True)
    for key in ("person", "tag", "folder", "search"):
        assert found[key] == newest, key


def test_timeline_and_trail_break_ties_by_hash():
    rows = _tied_rows()
    for row in rows:
        if isinstance(row, Photo):
            row.gps_latitude, row.gps_longitude = 52.0, 5.0

    async def body(client):
        timeline = (await client.get("/api/timeline", params={"group_by": "year"})).json()
        trail = (await client.get("/api/locations/trail")).json()
        return timeline, trail

    timeline, trail = run_with_client(body, rows)
    # Undated photos fall back to file_modified, the same instant here, and
    # come after the dated ones.
    dated = sorted(set(_SHUFFLED) - _UNDATED, reverse=True)
    assert [int(p["file_hash"], 16) for p in timeline[0]["photos"]] == dated + [9, 4]
    assert [int(p["file_hash"], 16) for p in trail[0]["photos"]] == sorted(
        set(_SHUFFLED) - _UNDATED
    )[:4]
