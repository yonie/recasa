"""Worker per-stage decisions: run, skip, record failure, route on."""

from datetime import datetime

import pytest
from sqlalchemy import select

from backend.app.exceptions import PermanentStageError
from backend.app.models import Caption, PhotoHash, StageFailure
from backend.app.workers import worker as worker_mod
from backend.app.workers.queues import Pipeline, QueueType
from backend.app.workers.worker import Worker

from .helpers import h, photo_row, touch_thumb


class FakeService:
    def __init__(self, exc: Exception | None = None):
        self.calls: list[str] = []
        self.exc = exc

    async def __call__(self, file_hash: str):
        self.calls.append(file_hash)
        if self.exc:
            raise self.exc
        return True


def _worker(monkeypatch, stage: QueueType, service: FakeService) -> tuple[Worker, Pipeline]:
    p = Pipeline()
    name = worker_mod.STAGE_SERVICES[stage][0]
    monkeypatch.setitem(worker_mod.STAGE_SERVICES, stage, (name, service))
    return Worker(p, stage), p


async def _add(db, *objs):
    async with db() as session:
        for o in objs:
            session.add_all(o) if isinstance(o, list) else session.add(o)
        await session.commit()


@pytest.mark.asyncio
async def test_runs_when_output_missing_then_routes_on(db, monkeypatch):
    fh = h(1)
    await _add(db, photo_row(fh))
    svc = FakeService()
    w, p = _worker(monkeypatch, QueueType.HASHING, svc)
    assert await w.process_item(fh)
    assert svc.calls == [fh]
    assert p.get_queue_sizes()["faces"] == 1


@pytest.mark.asyncio
async def test_skips_when_output_exists(db, monkeypatch):
    fh = h(2)
    await _add(db, photo_row(fh), PhotoHash(file_hash=fh, phash="0" * 16),
               Caption(file_hash=fh, caption=None, model=None))
    touch_thumb(fh)
    for stage in (QueueType.HASHING, QueueType.CAPTIONING, QueueType.THUMBNAILS, QueueType.EXIF):
        svc = FakeService()
        w, p = _worker(monkeypatch, stage, svc)
        assert await w.process_item(fh)
        assert svc.calls == []
        assert sum(p.get_queue_sizes().values()) == 1  # routed on


@pytest.mark.asyncio
async def test_skips_a_stage_with_a_recorded_failure(db, monkeypatch):
    fh = h(3)
    await _add(db, photo_row(fh), StageFailure(
        file_hash=fh, stage="thumbnails", error="cannot read image (OSError)",
        failed_at=datetime(2026, 1, 1),
    ))
    svc = FakeService()
    w, p = _worker(monkeypatch, QueueType.THUMBNAILS, svc)
    assert await w.process_item(fh)
    assert svc.calls == []
    assert p.get_queue_sizes()["motion_photos"] == 1


@pytest.mark.asyncio
async def test_permanent_error_is_recorded_transient_is_not(db, monkeypatch):
    fh_perm, fh_trans = h(4), h(5)
    await _add(db, photo_row(fh_perm), photo_row(fh_trans))

    w, p = _worker(monkeypatch, QueueType.HASHING, FakeService(PermanentStageError("bad")))
    assert await w.process_item(fh_perm)
    w2, p2 = _worker(monkeypatch, QueueType.HASHING, FakeService(ConnectionError("down")))
    assert await w2.process_item(fh_trans)

    async with db() as session:
        rows = (await session.execute(select(StageFailure.file_hash, StageFailure.stage))).all()
    assert rows == [(fh_perm, "hashing")]
    # Both still move on through the pipeline, and both are in the error log.
    assert p.get_queue_sizes()["faces"] == 1 and p2.get_queue_sizes()["faces"] == 1
    assert p.error_log[0]["error"] == "bad"
    assert w.queue.current_file_hash is None


@pytest.mark.asyncio
async def test_videos_only_get_thumbnails(db, monkeypatch):
    fh = h(6)
    await _add(db, photo_row(fh, is_video=True, date_taken=None))
    svc = FakeService()
    w, _ = _worker(monkeypatch, QueueType.EXIF, svc)
    await w.process_item(fh)
    assert svc.calls == []
    svc = FakeService()
    w, _ = _worker(monkeypatch, QueueType.THUMBNAILS, svc)
    await w.process_item(fh)
    assert svc.calls == [fh]


@pytest.mark.asyncio
async def test_geocoding_needs_gps_and_respects_switch(db, monkeypatch, stage_switches):
    no_gps, gps = h(7), h(8)
    await _add(db, photo_row(no_gps), photo_row(gps, gps_latitude=52.0, gps_longitude=5.0))
    svc = FakeService()
    w, _ = _worker(monkeypatch, QueueType.GEOCODING, svc)
    await w.process_item(no_gps)
    await w.process_item(gps)
    assert svc.calls == [gps]

    stage_switches.ENABLE_GEOCODING = False
    svc = FakeService()
    w, p = _worker(monkeypatch, QueueType.GEOCODING, svc)
    await w.process_item(gps)
    assert svc.calls == []
    assert p.get_queue_sizes()["thumbnails"] == 1


@pytest.mark.asyncio
async def test_missing_photo_is_dropped(db, monkeypatch):
    w, p = _worker(monkeypatch, QueueType.HASHING, FakeService())
    assert not await w.process_item(h(99))
    assert not any(p.get_queue_sizes().values())
    assert p.error_log[0]["error"] == "Photo not found in database"


@pytest.mark.asyncio
async def test_duplicate_detection_skipped_when_hashes_unchanged(db, monkeypatch):
    calls = []

    async def fake_find():
        calls.append(1)
        return []

    monkeypatch.setattr(worker_mod, "find_duplicates", fake_find)
    ew = worker_mod.EventDetectionWorker(Pipeline())
    await _add(db, photo_row(h(10)), PhotoHash(file_hash=h(10), phash="0" * 16))
    await ew._detect_duplicates()
    await ew._detect_duplicates()
    assert len(calls) == 1
    await _add(db, photo_row(h(11)), PhotoHash(file_hash=h(11), phash="f" * 16))
    await ew._detect_duplicates()
    assert len(calls) == 2


def test_ignored_stage_switches(monkeypatch):
    from backend.app.config import ignored_stage_switches

    monkeypatch.setenv("ENABLE_HASHING", "false")
    monkeypatch.setenv("ENABLE_THUMBNAILS", "true")
    monkeypatch.delenv("ENABLE_EXIF_EXTRACTION", raising=False)
    assert ignored_stage_switches() == ["ENABLE_HASHING"]
