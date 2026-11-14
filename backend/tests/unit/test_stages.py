"""The per-stage "does output exist?" rules and startup resume.

These rules decide what gets (re)processed. Getting one wrong either loses
work (a stage never runs) or re-runs weeks of face detection and captioning,
so each rule from AGENTS.md is pinned here.
"""

from datetime import datetime

import pytest

from backend.app.models import Caption, Face, PhotoHash, StageFailure
from backend.app.workers import pipeline as pipeline_mod
from backend.app.workers.queues import Pipeline, QueueType
from backend.app.workers.stages import (
    PhotoFacts,
    StageOutputs,
    first_needed_stage,
    load_photo_facts,
    load_stage_outputs,
)

from .helpers import h, photo_row, touch_thumb

Q = QueueType


def facts(fh="a", *, video=False, exif=True, gps=False, city=False) -> PhotoFacts:
    return PhotoFacts(fh, video, exif, gps, city)


def done(fh="a") -> StageOutputs:
    return StageOutputs(thumbs={fh}, hashed={fh}, faced={fh}, captioned={fh})


@pytest.mark.parametrize(
    ("photo", "outputs", "expected"),
    [
        # Nothing done yet: EXIF first.
        (facts(exif=False), StageOutputs(), Q.EXIF),
        # EXIF done (camera_make or date_taken), no GPS: geocoding does not apply.
        (facts(), StageOutputs(), Q.THUMBNAILS),
        # GPS but no city: geocoding.
        (facts(gps=True), StageOutputs(), Q.GEOCODING),
        (facts(gps=True, city=True), StageOutputs(), Q.THUMBNAILS),
        (facts(), StageOutputs(thumbs={"a"}), Q.HASHING),
        (facts(), StageOutputs(thumbs={"a"}, hashed={"a"}), Q.FACES),
        (facts(), StageOutputs(thumbs={"a"}, hashed={"a"}, faced={"a"}), Q.CAPTIONING),
        (facts(), done(), None),
        # Videos only ever need a poster thumbnail.
        (facts(video=True, exif=False, gps=True), StageOutputs(), Q.THUMBNAILS),
        (facts(video=True, exif=False), StageOutputs(thumbs={"a"}), None),
    ],
)
def test_first_needed_stage(stage_switches, photo, outputs, expected):
    assert outputs.first_needed_stage(photo) == expected


def test_failed_stages_are_passed_over(stage_switches):
    outputs = StageOutputs(failures={"a": {"thumbnails", "hashing"}})
    # Unreadable file: thumbnails and hashing failed for good, faces still due.
    assert outputs.first_needed_stage(facts()) == Q.FACES
    outputs.faced.add("a")
    outputs.captioned.add("a")
    assert outputs.first_needed_stage(facts()) is None
    video = StageOutputs(failures={"a": {"thumbnails"}})
    assert video.first_needed_stage(facts(video=True)) is None


def test_disabled_stages_are_never_needed(stage_switches):
    stage_switches.ENABLE_GEOCODING = False
    stage_switches.ENABLE_FACE_DETECTION = False
    stage_switches.ENABLE_CAPTIONING = False
    outputs = StageOutputs(thumbs={"a"}, hashed={"a"})
    assert outputs.first_needed_stage(facts(gps=True)) is None


async def _seed(session_factory, *objs):
    async with session_factory() as session:
        for o in objs:
            if isinstance(o, list):
                session.add_all(o)
            else:
                session.add(o)
        await session.commit()


@pytest.mark.asyncio
async def test_bulk_and_single_loads_agree(db):
    fh_done, fh_new, fh_failed = h(1), h(2), h(3)
    await _seed(
        db,
        photo_row(fh_done), photo_row(fh_new, date_taken=None), photo_row(fh_failed),
        PhotoHash(file_hash=fh_done, phash="0" * 16),
        Face(file_hash=fh_done, bbox_x=0, bbox_y=0, bbox_w=0, bbox_h=0, encoding=None),
        Caption(file_hash=fh_done, caption=None, model=None),
        StageFailure(file_hash=fh_failed, stage="thumbnails", error="x",
                     failed_at=datetime(2026, 1, 1)),
        StageFailure(file_hash=fh_failed, stage="hashing", error="x",
                     failed_at=datetime(2026, 1, 1)),
    )
    touch_thumb(fh_done)

    async with db() as session:
        bulk = await load_stage_outputs(session)
        all_facts = {f.file_hash: f for f in await load_photo_facts(session)}
        for fh in (fh_done, fh_new, fh_failed):
            from backend.app.models import Photo

            photo = await session.get(Photo, fh)
            assert await first_needed_stage(session, photo) == bulk.first_needed_stage(
                all_facts[fh]
            )

    assert bulk.first_needed_stage(all_facts[fh_done]) is None
    assert bulk.first_needed_stage(all_facts[fh_new]) == Q.EXIF
    # Marker rows count as output: a NULL-encoding face and a NULL caption.
    assert bulk.first_needed_stage(all_facts[fh_failed]) == Q.FACES


@pytest.mark.asyncio
async def test_resume_queues_each_photo_once_at_its_first_needed_stage(db, monkeypatch, caplog):
    fresh = Pipeline()
    monkeypatch.setattr(pipeline_mod, "pipeline", fresh)

    fh_complete, fh_no_exif, fh_no_thumb, fh_unreadable, fh_video = (h(i) for i in range(1, 6))
    full = lambda fh: [
        PhotoHash(file_hash=fh, phash="0" * 16),
        Face(file_hash=fh, bbox_x=0, bbox_y=0, bbox_w=0, bbox_h=0, encoding=None),
        Caption(file_hash=fh, caption="c", model="m"),
    ]
    failed = lambda fh, stage: StageFailure(
        file_hash=fh, stage=stage, error="cannot read image (UnidentifiedImageError)",
        failed_at=datetime(2026, 1, 1),
    )
    await _seed(
        db,
        photo_row(fh_complete), *full(fh_complete),
        photo_row(fh_no_exif, date_taken=None), *full(fh_no_exif),
        photo_row(fh_no_thumb), *full(fh_no_thumb),
        # The Pi's 13 unreadable files: no thumbnail, no hash, both recorded
        # as permanent failures. Resume must leave them alone.
        photo_row(fh_unreadable), failed(fh_unreadable, "thumbnails"),
        failed(fh_unreadable, "hashing"),
        Face(file_hash=fh_unreadable, bbox_x=0, bbox_y=0, bbox_w=0, bbox_h=0, encoding=None),
        Caption(file_hash=fh_unreadable, caption=None, model=None),
        photo_row(fh_video, is_video=True, date_taken=None),
    )
    for fh in (fh_complete, fh_no_exif):
        touch_thumb(fh)

    caplog.set_level("INFO")
    queued = await pipeline_mod.resume_incomplete_processing()

    sizes = fresh.get_queue_sizes()
    assert queued == 3
    assert sizes["exif"] == 1
    assert sizes["thumbnails"] == 2  # fh_no_thumb and the video poster
    assert sum(sizes.values()) == 3
    assert "Found 0 photos needing hashing" in caplog.text
    assert "Found 2 photos needing thumbnails" in caplog.text
    assert "Skipping 2 photo/stage pairs with recorded failures" in caplog.text


@pytest.mark.asyncio
async def test_resume_skips_disabled_stages(db, monkeypatch, stage_switches):
    fresh = Pipeline()
    monkeypatch.setattr(pipeline_mod, "pipeline", fresh)
    stage_switches.ENABLE_CAPTIONING = False
    fh = h(9)
    await _seed(
        db, photo_row(fh), PhotoHash(file_hash=fh, phash="0" * 16),
        Face(file_hash=fh, bbox_x=0, bbox_y=0, bbox_w=0, bbox_h=0, encoding=None),
    )
    touch_thumb(fh)
    assert await pipeline_mod.resume_incomplete_processing() == 0
