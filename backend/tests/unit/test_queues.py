"""Queue routing and the state /api/pipeline/* reads from the pipeline."""

import re
from itertools import pairwise

import pytest

from backend.app.workers.queues import PIPELINE_ORDER, Pipeline, QueueType


def test_every_stage_routes_to_the_next():
    p = Pipeline()
    order = [q.value for q in PIPELINE_ORDER]
    assert order == [
        "exif", "geocoding", "thumbnails", "motion_photos",
        "hashing", "faces", "captioning", "events",
    ]
    for a, b in pairwise(PIPELINE_ORDER):
        assert p.get_next_queues(a) == [b]
    assert p.get_next_queues(QueueType.EVENTS) == []


@pytest.mark.asyncio
async def test_route_to_next_and_drain():
    p = Pipeline()
    await p.add_file_at("x", QueueType.HASHING)
    await p.route_to_next("x", QueueType.HASHING)
    assert p.get_queue_sizes() == {
        "exif": 0, "geocoding": 0, "thumbnails": 0, "motion_photos": 0,
        "hashing": 1, "faces": 1, "captioning": 0, "events": 0,
    }
    p.stop_and_drain()
    assert p._stop_requested
    assert not any(p.get_queue_sizes().values())


def test_queue_info_shape():
    p = Pipeline()
    p.queues[QueueType.FACES].current_file_hash = "abc"
    p.queues[QueueType.FACES].current_file_path = "/photos/a.jpg"
    info = p.get_queue_info()
    assert list(info) == [q.value for q in QueueType]
    assert info["faces"] == {
        "queue_type": "faces", "pending": 0, "processing": 1,
        "current_file_hash": "abc", "current_file_path": "/photos/a.jpg",
    }
    assert info["exif"]["processing"] == 0


def test_error_log_is_capped_and_keeps_its_format():
    p = Pipeline()
    for i in range(150):
        p.add_error("hashing", f"h{i}", None, "x" * 300)
    assert len(p.error_log) == 100
    assert p.error_log[0]["file_hash"] == "h50"
    entry = p.error_log[-1]
    assert set(entry) == {"timestamp", "queue", "file_hash", "file_path", "error"}
    assert len(entry["error"]) == 200
    # Naive ISO timestamp, as datetime.utcnow().isoformat() used to give.
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?", entry["timestamp"])


@pytest.mark.asyncio
async def test_full_queue_drops_instead_of_blocking():
    p = Pipeline()
    q = p.queues[QueueType.EXIF]
    small = type(q)(QueueType.EXIF, max_size=1)
    assert await small.put("a")
    assert not await small.put("b")
