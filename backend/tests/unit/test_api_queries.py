"""Shared photo-grid queries, filters and the endpoints built on them."""

import sys
from pathlib import Path

from sqlalchemy import select, update

sys.path.insert(0, str(Path(__file__).parent))

from api_fixtures import h, run_with_client, run_with_session  # noqa: E402

from backend.app.api.directories import build_directory_tree  # noqa: E402
from backend.app.models import Photo, PhotoTag  # noqa: E402
from backend.app.queries.filters import (  # noqa: E402
    date_search_condition,
    library_conditions,
)
from backend.app.queries.photos import (  # noqa: E402
    NEWEST_FIRST,
    VISIBLE,
    photo_page,
    summary_select,
    to_summary,
)
from backend.app.queries.tags import (  # noqa: E402
    hidden_tagged_hashes,
    tag_counts,
    tag_counts_query,
)


def _matching(**filters) -> set[int]:
    """Numbers of the seeded photos that library_conditions(**filters) selects."""

    async def body(session):
        rows = await session.execute(
            select(Photo.file_hash).where(*library_conditions(**filters))
        )
        return {int(fh, 16) for (fh,) in rows}

    return run_with_session(body)


# --- filters ---------------------------------------------------------------


def test_date_search_condition_needs_a_year_or_month():
    assert date_search_condition("beach dog") is None
    assert date_search_condition("12345") is None  # not a 4-digit year in range
    assert date_search_condition("1800") is None
    assert date_search_condition("2019") is not None
    assert date_search_condition("Sept") is not None


def test_visible_by_default_flagged_only_on_request():
    assert _matching() == {1, 2, 3, 5, 6, 7, 8, 9, 10}
    assert _matching(flagged=True) == {4}
    assert _matching(flagged=False) == _matching()


def test_flag_filters():
    assert _matching(favorite=True) == {1}
    assert _matching(marked_for_print=True) == {3}
    assert _matching(video=True) == {5}
    assert 5 not in _matching(video=False)


def test_place_and_date_filters():
    from datetime import datetime

    assert _matching(country="NL") == {1, 2}
    assert _matching(country="NL", city="Amsterdam") == {1, 2}
    assert _matching(city="Utrecht") == set()
    assert _matching(date_from=datetime(2020, 1, 1)) == {1, 2, 3, 10}
    assert _matching(date_to=datetime(2019, 12, 31)) == {6, 7, 8}


def test_search_matches_every_source():
    assert _matching(search="beach") == {1, 10}  # caption + tag; 4 is flagged
    assert _matching(search="DOG") == {1, 2}  # case-insensitive caption and tag
    assert _matching(search="lise") == {6, 7, 8}  # person name
    assert _matching(search="amsterdam") == {1, 2}  # place
    assert _matching(search="clip") == {5}  # file name
    assert _matching(search="album") == {1, 2, 3, 6, 7, 10}  # path
    assert _matching(search="zzzz") == set()


def test_search_by_date_words():
    assert _matching(search="2019") == {6, 7, 8}
    assert _matching(search="august 2019") == {6, 7}
    assert _matching(search="dec") == {8}
    # Every date word must hold; the text match is on the whole phrase.
    assert _matching(search="2019 may") == set()
    assert _matching(search="eva 2020") == {1, 2, 3}


def test_search_keeps_like_wildcards():
    # "_" and "%" have always been LIKE wildcards in the search box.
    assert _matching(search="IMG_000") == {1, 2, 3, 6, 7, 8}
    assert _matching(search="%") == _matching()


# --- summaries and paging -------------------------------------------------


def test_to_summary_carries_every_tile_field():
    async def body(session):
        row = (await session.execute(summary_select().where(Photo.file_hash == h(5)))).one()
        return to_summary(row)

    summary = run_with_session(body)
    assert summary.is_video is True and summary.duration == 4.5
    assert summary.marked_for_print is False and summary.flagged_for_removal is False
    assert summary.thumbnail_url == f"/api/photos/{h(5)}/thumbnail/600"
    assert summary.file_name == "clip.mp4"


def test_to_summary_live_photo():
    async def body(session):
        rows = await session.execute(
            summary_select().where(Photo.file_hash.in_([h(10), h(1)])).order_by(Photo.file_hash)
        )
        return [to_summary(r).has_live_photo for r in rows]

    assert run_with_session(body) == [False, True]


def test_photo_page_counts_and_pages():
    async def body(session):
        stmt = summary_select().where(VISIBLE)
        first = await photo_page(session, stmt, order_by=NEWEST_FIRST, page=1, page_size=4)
        last = await photo_page(session, stmt, order_by=NEWEST_FIRST, page=3, page_size=4)
        beyond = await photo_page(session, stmt, order_by=NEWEST_FIRST, page=9, page_size=4)
        return first, last, beyond

    first, last, beyond = run_with_session(body)
    assert first.total == last.total == beyond.total == 9
    assert [int(p.file_hash, 16) for p in first.items] == [10, 3, 2, 1]
    assert first.has_more and not last.has_more and not beyond.has_more
    # Undated photos (5 and 9) sort last when newest first.
    assert len(last.items) == 1 and int(last.items[0].file_hash, 16) in {5, 9}
    assert beyond.items == []


# --- tags -----------------------------------------------------------------


def _tag_rows(**kw):
    """Rows by both routes, checked to agree."""

    async def body(session):
        fast = await tag_counts(session, **kw)
        joined = (await session.execute(tag_counts_query(**kw))).all()
        assert [tuple(r) for r in fast] == [tuple(r) for r in joined]
        return fast

    return run_with_session(body)


def test_tag_counts_subtract_orphans_and_flagged():
    async def body(session):
        # A tag row for a photo that is no longer indexed must not count.
        session.add(PhotoTag(file_hash=h(99), tag_id=3))
        session.add(PhotoTag(file_hash=h(99), tag_id=7))  # and an unknown tag id
        await session.commit()
        hidden = await hidden_tagged_hashes(session)
        fast = await tag_counts(session, limit=10)
        joined = (await session.execute(tag_counts_query(limit=10))).all()
        return hidden, fast, joined

    hidden, fast, joined = run_with_session(body)
    assert hidden == [h(4), h(99)]
    assert [tuple(r) for r in fast] == [tuple(r) for r in joined]
    assert [(r.name, r.count) for r in fast] == [("dog", 2), ("beach", 1), ("sunny beach", 1)]


def test_tag_counts_skip_flagged_and_rank():
    rows = _tag_rows(limit=10)
    # beach: photo 1 only (4 is flagged); dog: 1 and 2; sunny beach: 10.
    assert [(r.name, r.count) for r in rows] == [("dog", 2), ("beach", 1), ("sunny beach", 1)]
    assert {r.total for r in rows} == {3}


def test_tag_counts_limit_keeps_total_and_name_filter():
    rows = _tag_rows(limit=1)
    assert [(r.name, r.total) for r in rows] == [("dog", 3)]
    rows = _tag_rows(limit=10, name_contains="BEACH")
    assert [r.name for r in rows] == ["beach", "sunny beach"]
    assert rows[0].total == 2
    assert _tag_rows(limit=10, name_contains="nothing") == []


def test_tag_listing_endpoint():
    async def body(client):
        return (await client.get("/api/tags", params={"q": "beach"})).json()

    data = run_with_client(body)
    assert data == {
        "items": [
            {"tag_id": 1, "name": "beach", "category": None, "count": 1},
            {"tag_id": 2, "name": "sunny beach", "category": None, "count": 1},
        ],
        "total": 2,
    }


# --- directories ----------------------------------------------------------


def test_directory_tree_counts_and_skips():
    tree = build_directory_tree(
        ["a/b/1.jpg", "a/b/2.jpg", "a/3.jpg", "a\\c\\4.jpg", "root.jpg", "_hidden/5.jpg",
         "a/_private/6.jpg"]
    )
    assert [(n.name, n.path, n.photo_count) for n in tree] == [("a", "a", 5)]
    assert [(n.name, n.path, n.photo_count) for n in tree[0].children] == [
        ("b", "a/b", 2),
        ("c", "a/c", 1),
    ]


# --- endpoints over the shared layer --------------------------------------


def test_person_photos_and_together():
    async def body(client):
        person = (await client.get("/api/persons/1/photos")).json()
        pair = (await client.get("/api/persons/groups/together/1/2/photos")).json()
        trio = (await client.get("/api/persons/groups/together-n/photos",
                                 params={"person_ids": "1,2,3"})).json()
        groups = (await client.get("/api/persons/groups/together",
                                   params={"min_photos": 2})).json()
        return person, pair, trio, groups

    person, pair, trio, groups = run_with_client(body)
    assert person["total"] == 3
    assert [int(p["file_hash"], 16) for p in person["items"]] == [8, 7, 6]
    # Exactly these people: photo 8 also has Bob, so it is not a Lise+Eva photo.
    assert [int(p["file_hash"], 16) for p in pair["items"]] == [6]
    assert [int(p["file_hash"], 16) for p in trio["items"]] == [8]
    assert groups == []  # no pair shares two photos


def test_timeline_pages_groups_and_keeps_order():
    async def body(client):
        full = (await client.get("/api/timeline", params={"group_by": "month"})).json()
        page = (await client.get("/api/timeline",
                                 params={"group_by": "month", "offset": 1, "limit": 2})).json()
        years = (await client.get("/api/timeline", params={"group_by": "year"})).json()
        return full, page, years

    full, page, years = run_with_client(body)
    keys = [g["date"] for g in full]
    assert keys == ["2021-01", "2020-06", "2020-05", "2019-12", "2019-08", "2018-03", "unknown"]
    assert page == full[1:3]
    may = full[2]
    assert may["count"] == 2 and [int(p["file_hash"], 16) for p in may["photos"]] == [2, 1]
    assert [g["date"] for g in years] == ["2021", "2020", "2019", "2018", "unknown"]
    assert full[-1]["photos"][0]["file_name"] == "loose.jpg"


def test_stats_endpoint():
    async def body(client):
        return (await client.get("/api/photos/stats")).json()

    stats = run_with_client(body)
    assert stats["total_photos"] == 8  # visible, not video
    assert stats["videos_count"] == 1
    assert stats["favorites_count"] == 1 and stats["to_print_count"] == 1
    assert stats["flagged_count"] == 1
    assert stats["total_persons"] == 3 and stats["total_tags"] == 3
    assert stats["oldest_photo"].startswith("2019-08-10")
    assert stats["newest_photo"].startswith("2021-01-01")
    assert stats["locations_count"] == 1


def test_persons_listing_links_thumbnails_only_with_a_crop():
    async def body(client):
        return (await client.get("/api/persons")).json()

    persons = run_with_client(body)
    assert [(p["person_id"], p["face_thumbnail_url"]) for p in persons] == [
        (1, "/api/persons/1/thumbnail"),
        (2, None),  # representative face has no crop on record
        (3, None),
    ]


def test_event_cover_hidden_when_flagged():
    async def body(client):
        return (await client.get("/api/events")).json(), (await client.get("/api/events/1")).json()

    listing, single = run_with_client(body)
    assert listing[0]["cover_photo"] is None and single["cover_photo"] is None


def test_tag_counts_with_nothing_hidden():
    async def body(session):
        await session.execute(update(Photo).values(flagged_for_removal=False))
        await session.commit()
        hidden = await hidden_tagged_hashes(session)
        fast = await tag_counts(session, limit=10)
        joined = (await session.execute(tag_counts_query(limit=10))).all()
        return hidden, fast, joined

    hidden, fast, joined = run_with_session(body)
    assert hidden == []
    assert [tuple(r) for r in fast] == [tuple(r) for r in joined]
    assert [(r.name, r.count) for r in fast] == [("beach", 2), ("dog", 2), ("sunny beach", 1)]
