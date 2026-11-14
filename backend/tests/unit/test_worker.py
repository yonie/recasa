"""Worker per-stage decisions: run, skip, record failure, route on."""

import asyncio
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


@pytest.mark.asyncio
async def test_stop_ends_the_item_in_hand_and_later_work_still_runs(db, monkeypatch):
    fh, fh2 = h(20), h(21)
    await _add(db, photo_row(fh), photo_row(fh2))

    class StopDuring(FakeService):
        async def __call__(self, file_hash: str):
            if not self.calls:
                p.stop_and_drain()  # Stop pressed while this photo is hashed
            return await super().__call__(file_hash)

    svc = StopDuring()
    w, p = _worker(monkeypatch, QueueType.HASHING, svc)
    await p.add_file_at(fh2, QueueType.HASHING)
    await w.process_item(fh)
    assert p._stop_requested
    assert not any(p.get_queue_sizes().values())  # drained, fh not routed on

    # Resume: the worker loop is still alive and processes new work.
    p.begin_work()
    assert not p._stop_requested
    task = asyncio.create_task(w.run())
    await p.add_file_at(fh2, QueueType.HASHING)
    for _ in range(100):
        if p.get_queue_sizes()["faces"]:
            break
        await asyncio.sleep(0.02)
    w.stop()
    await asyncio.wait_for(task, 3)
    assert svc.calls == [fh, fh2]
    assert p.get_queue_sizes()["faces"] == 1


@pytest.mark.asyncio
async def test_a_scan_after_stop_runs_and_a_stop_cancels_only_the_running_scan(
    db, photos_dir, monkeypatch
):
    from backend.app.services import scanner
    from backend.app.workers import pipeline as pipeline_mod
    from backend.app.workers.queues import pipeline

    from .helpers import write_jpeg

    write_jpeg(photos_dir / "a.jpg", seed=50)
    pipeline.stop_and_drain()
    stats = await pipeline_mod.run_initial_scan()
    assert stats["new"] == 1 and not pipeline._stop_requested
    assert pipeline.get_queue_sizes()["exif"] == 1

    # Stop during a scan: it is cancelled before indexing anything.
    write_jpeg(photos_dir / "b.jpg", seed=51)
    real_collect = scanner._collect_photo_files

    def collect_then_stop(*args):
        result = real_collect(*args)
        pipeline.stop_and_drain()
        return result

    monkeypatch.setattr(scanner, "_collect_photo_files", collect_then_stop)
    stats = await pipeline_mod.run_initial_scan()
    assert stats["new"] == 0 and pipeline._stop_requested
    monkeypatch.setattr(scanner, "_collect_photo_files", real_collect)
    stats = await pipeline_mod.run_initial_scan()
    assert stats["new"] == 1
    pipeline.stop_and_drain()
    pipeline.begin_work()


@pytest.mark.asyncio
async def test_geocoding_takes_zero_coordinates_and_skips_half_a_position(
    db, monkeypatch, stage_switches
):
    from backend.app.services import geocoder
    from backend.app.workers.stages import load_photo_facts, load_stage_outputs

    equator, lat_only = h(9), h(10)
    await _add(db, photo_row(equator, gps_latitude=0.0, gps_longitude=9.5),
               photo_row(lat_only, gps_latitude=52.0))

    # Half a position never enters geocoding, so it is not re-queued forever.
    async with db() as session:
        facts = {f.file_hash: f for f in await load_photo_facts(session)}
        outputs = await load_stage_outputs(session)
    assert outputs.first_needed_stage(facts[equator]) is QueueType.GEOCODING
    assert outputs.first_needed_stage(facts[lat_only]) is QueueType.THUMBNAILS
    svc = FakeService()
    w, _ = _worker(monkeypatch, QueueType.GEOCODING, svc)
    await w.process_item(lat_only)
    assert svc.calls == []

    class FakeGeocoder:
        @staticmethod
        def search(coords, mode, verbose):
            assert coords == [(0.0, 9.5)]
            return [{"name": "Libreville", "cc": "GA", "admin1": "Estuaire"}]

    monkeypatch.setattr(geocoder, "_geocoder", FakeGeocoder)
    assert await geocoder.geocode_photo(equator)
    assert not await geocoder.geocode_photo(lat_only)
    async with db() as session:
        photo = await session.get(worker_mod.Photo, equator)
    assert photo.location_address == "Libreville, Estuaire, GA"


@pytest.mark.asyncio
async def test_debounced_event_detection_still_runs_after_the_last_batch(monkeypatch):
    """A batch inside MIN_EVENT_INTERVAL of the previous one used to skip
    event detection for good when no further photo came."""
    calls = []

    async def fake_detect():
        calls.append(1)

    async def nothing():
        return None

    monkeypatch.setattr(worker_mod, "detect_events", fake_detect)
    monkeypatch.setattr(worker_mod.settings, "ENABLE_FACE_DETECTION", False)
    ew = worker_mod.EventDetectionWorker(Pipeline())
    monkeypatch.setattr(ew, "_detect_duplicates", nothing)
    await ew._run_batch()
    await ew._run_batch()  # within the interval: deferred, not dropped
    assert calls == [1] and ew._events_pending

    ew.MIN_EVENT_INTERVAL = 0.05
    ew.SETTLE_SECONDS = 0
    monkeypatch.setattr(worker_mod.asyncio, "sleep", _fast_sleep)
    task = asyncio.create_task(ew.run())
    for _ in range(200):
        if len(calls) == 2:
            break
        await _real_sleep(0.01)
    ew.stop()
    await asyncio.wait_for(task, 3)
    assert calls == [1, 1] and not ew._events_pending


_real_sleep = asyncio.sleep


async def _fast_sleep(seconds):
    await _real_sleep(min(seconds, 0.01))
