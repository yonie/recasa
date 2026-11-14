"""File watcher: one debounced index per written file, library paths only."""

import asyncio
from types import SimpleNamespace

import pytest

from backend.app.workers import pipeline as pipeline_mod
from backend.app.workers.queues import Pipeline


def _event(path, dest=None, directory=False):
    return SimpleNamespace(src_path=str(path), dest_path=str(dest) if dest else "",
                           is_directory=directory)


@pytest.mark.asyncio
async def test_burst_of_events_indexes_once_after_quiet(photos_dir, monkeypatch):
    calls = []

    async def fake_index(path):
        calls.append(path)
        return ("f" * 64, "exif")

    monkeypatch.setattr(pipeline_mod, "index_single_file", fake_index)
    fresh = Pipeline()
    monkeypatch.setattr(pipeline_mod, "pipeline", fresh)
    monkeypatch.setattr(pipeline_mod.FileEventHandler, "QUIET_SECONDS", 0.05)

    target = photos_dir / "2024" / "new.jpg"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"x" * 2048)
    handler = pipeline_mod.FileEventHandler(asyncio.get_running_loop())

    handler.on_created(_event(target))
    for _ in range(5):
        handler.on_modified(_event(target))
        await asyncio.sleep(0.01)
    handler.on_closed(_event(target))
    # Renamed into place by a sync tool:
    renamed = photos_dir / "2024" / "synced.jpg"
    renamed.write_bytes(b"y" * 2048)
    handler.on_moved(_event(photos_dir / "2024" / ".syncthing.synced.jpg.tmp", renamed))
    # Not library photos: ignored outright.
    handler.on_created(_event(photos_dir / ".stversions" / "old.jpg"))
    handler.on_created(_event(photos_dir / "2024" / "notes.txt"))
    handler.on_created(_event(photos_dir / "2024", directory=True))

    await asyncio.sleep(0.3)
    assert sorted(p.name for p in calls) == ["new.jpg", "synced.jpg"]
    assert fresh.get_queue_sizes()["exif"] == 2
