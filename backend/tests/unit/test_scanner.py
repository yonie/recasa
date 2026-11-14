"""Scanner change detection, indexing and cleanup against a temp library."""

import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

from backend.app.models import Caption, Face, Photo, PhotoHash, PhotoPath
from backend.app.services import scanner
from backend.app.services.scanner import (
    _is_live_photo_companion,
    compute_file_hash,
    index_single_file,
    is_hidden_path,
    scan_directory,
)

from .helpers import set_mtime, touch_thumb, write_jpeg


class Discovered:
    def __init__(self):
        self.items: list[tuple[str, str]] = []

    async def __call__(self, file_hash: str, stage: str):
        self.items.append((file_hash, stage))


async def _paths(db) -> dict[str, str]:
    async with db() as session:
        rows = (await session.execute(select(PhotoPath.file_path, PhotoPath.file_hash))).all()
    return dict(rows)


async def _photos(db) -> dict[str, Photo]:
    async with db() as session:
        return {p.file_hash: p for p in (await session.execute(select(Photo))).scalars()}


@pytest.mark.asyncio
async def test_new_photos_enter_at_exif_and_unchanged_ones_are_skipped(db, photos_dir):
    a = write_jpeg(photos_dir / "2024" / "a.jpg", seed=1)
    write_jpeg(photos_dir / "2024" / "b.jpg", seed=2)
    found = Discovered()
    stats = await scan_directory(on_file_discovered=found)
    assert (stats["total"], stats["new"], stats["errors"]) == (2, 2, 0)
    assert sorted(stage for _, stage in found.items) == ["exif", "exif"]
    assert set(await _paths(db)) == {"2024/a.jpg", "2024/b.jpg"}

    # Periodic sweep with nothing changed: nothing indexed or queued.
    found = Discovered()
    stats = await scan_directory(on_file_discovered=found, fast=True)
    assert stats["new"] == 0 and found.items == []

    # A full rescan re-queues unchanged photos at their first missing stage.
    async with db() as session:
        photo = await session.get(Photo, compute_file_hash(a))
        photo.date_taken = photo.file_modified  # EXIF done
        await session.commit()
    found = Discovered()
    await scan_directory(on_file_discovered=found)
    assert (compute_file_hash(a), "thumbnails") in found.items


@pytest.mark.asyncio
async def test_fully_processed_photo_is_not_queued_by_full_rescan(db, photos_dir, stage_switches):
    a = write_jpeg(photos_dir / "a.jpg", seed=3)
    await scan_directory()
    fh = compute_file_hash(a)
    async with db() as session:
        (await session.get(Photo, fh)).camera_make = "X"
        session.add_all([
            PhotoHash(file_hash=fh, phash="0" * 16),
            Face(file_hash=fh, bbox_x=0, bbox_y=0, bbox_w=0, bbox_h=0, encoding=None),
            Caption(file_hash=fh, caption=None, model=None),
        ])
        await session.commit()
    touch_thumb(fh)
    found = Discovered()
    stats = await scan_directory(on_file_discovered=found)
    assert found.items == []
    assert stats["skipped"] == 1


@pytest.mark.asyncio
async def test_changed_file_is_rehashed(db, photos_dir):
    a = write_jpeg(photos_dir / "a.jpg", seed=4)
    await scan_directory()
    old = compute_file_hash(a)
    write_jpeg(a, seed=5)
    set_mtime(a, a.stat().st_mtime + 10)
    found = Discovered()
    await scan_directory(on_file_discovered=found)
    new = compute_file_hash(a)
    assert (new, "exif") in found.items
    # In-place edits keep the old version's row (see report); scanning again
    # must not trip over the path now holding two photos.
    stats = await scan_directory()
    assert stats["errors"] == 0
    assert set((await _photos(db))) == {old, new}


@pytest.mark.asyncio
async def test_removed_files_are_cleaned_up(db, photos_dir):
    write_jpeg(photos_dir / "keep.jpg", seed=6)
    gone = write_jpeg(photos_dir / "gone.jpg", seed=7)
    await scan_directory()
    gone.unlink()
    await scan_directory(fast=True)
    assert set(await _paths(db)) == {"keep.jpg"}
    assert len(await _photos(db)) == 1


@pytest.mark.asyncio
async def test_cleanup_refuses_an_empty_library(db, photos_dir):
    write_jpeg(photos_dir / "a.jpg", seed=8)
    await scan_directory()
    for p in photos_dir.iterdir():
        p.unlink()
    await scan_directory()
    assert set(await _paths(db)) == {"a.jpg"}


@pytest.mark.asyncio
async def test_moved_primary_copy_is_repointed(db, photos_dir):
    a = write_jpeg(photos_dir / "x" / "a.jpg", seed=9)
    await scan_directory()
    fh = compute_file_hash(a)
    copy = photos_dir / "y" / "a.jpg"
    copy.parent.mkdir()
    shutil.copy2(a, copy)
    await scan_directory()
    assert (await _photos(db))[fh].file_path == "x/a.jpg"

    a.unlink()
    await scan_directory()
    photos = await _photos(db)
    assert set(await _paths(db)) == {"y/a.jpg"}
    assert photos[fh].file_path == "y/a.jpg"


@pytest.mark.asyncio
async def test_sweep_with_no_directory_changes_skips_db_work(db, photos_dir, monkeypatch):
    write_jpeg(photos_dir / "d" / "a.jpg", seed=10)
    await scan_directory(fast=True)  # first sweep after start: stats everything

    async def boom():
        raise AssertionError("known paths should not be loaded")

    monkeypatch.setattr(scanner, "_load_known_paths", boom)
    stats = await scan_directory(fast=True)
    assert stats["total"] == 1 and stats["errors"] == 0


@pytest.mark.asyncio
async def test_hidden_directories_are_not_indexed(db, photos_dir):
    write_jpeg(photos_dir / ".stversions" / "old.jpg", seed=11)
    visible = write_jpeg(photos_dir / "new.jpg", seed=12)
    stats = await scan_directory()
    assert stats["total"] == 1
    hidden = photos_dir / ".stversions" / "old.jpg"
    assert await index_single_file(hidden) is None
    assert is_hidden_path(".stversions/x.jpg") and not is_hidden_path("2024/x.jpg")
    assert set(await _paths(db)) == {"new.jpg"}
    assert visible.exists()


@pytest.mark.asyncio
async def test_watcher_indexing(db, photos_dir):
    a = write_jpeg(photos_dir / "w.jpg", seed=13)
    result = await index_single_file(a)
    assert result == (compute_file_hash(a), "exif")
    # Seen again (a late modified event): no new row, same entry stage.
    assert await index_single_file(a) == result
    assert len(await _photos(db)) == 1
    tiny = photos_dir / "tiny.jpg"
    tiny.write_bytes(b"\xff\xd8 not really")
    assert await index_single_file(tiny) is None


def test_live_photo_companion_detection(tmp_path: Path):
    mov = tmp_path / "IMG_1.MOV"
    mov.write_bytes(b"x")
    assert not _is_live_photo_companion(mov)
    (tmp_path / "IMG_1.HEIC").write_bytes(b"x")
    assert _is_live_photo_companion(mov)
    assert _is_live_photo_companion(mov, {"IMG_1.MOV", "IMG_1.HEIC"})
    # The sibling listing only short-cuts a hit; a miss still checks the disk.
    assert _is_live_photo_companion(mov, {"IMG_1.MOV"})
    assert not _is_live_photo_companion(tmp_path / "clip.mp4", {"clip.jpg"})


def test_file_hash_is_sha256(tmp_path: Path):
    import hashlib

    p = tmp_path / "f"
    p.write_bytes(b"abc" * 100000)
    assert compute_file_hash(p) == hashlib.sha256(p.read_bytes()).hexdigest()
