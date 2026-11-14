"""Scanner change detection, indexing and cleanup against a temp library."""

import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

from backend.app.models import Caption, Face, Photo, PhotoHash, PhotoPath, PhotoTag, Tag
from backend.app.services import scanner
from backend.app.services.scanner import (
    _is_live_photo_companion,
    compute_file_hash,
    index_single_file,
    is_library_path,
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
async def test_multi_path_hash_loses_only_the_vanished_path(db, photos_dir):
    a = write_jpeg(photos_dir / "one" / "a.jpg", seed=19)
    b = photos_dir / "two" / "a.jpg"
    b.parent.mkdir()
    shutil.copy2(a, b)
    await scan_directory()
    fh = compute_file_hash(a)
    async with db() as session:
        session.add(Caption(file_hash=fh, caption="keep me", model="m"))
        await session.commit()
    b.unlink()
    await scan_directory(fast=True)
    assert set(await _paths(db)) == {"one/a.jpg"}
    async with db() as session:
        assert (await session.get(Caption, fh)).caption == "keep me"
        assert (await session.get(Photo, fh)).file_path == "one/a.jpg"


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


@pytest.mark.parametrize(
    ("path", "ok"),
    [
        ("2024/IMG_1.jpg", True),
        ("2024/~not-syncthing.jpg", True),
        (".stversions/2026/P9123781~20260918-072229.ORF", False),
        ("2024/.hidden/a.jpg", False),
        ("2024/.a.jpg", False),
        ("2024/._IMG_1.jpg", False),  # macOS AppleDouble
        ("2024/~syncthing~IMG_1.jpg.tmp", False),
        ("2024/.syncthing.IMG_1.jpg.tmp", False),
    ],
)
def test_library_path_predicate(path, ok):
    assert is_library_path(path) is ok


@pytest.mark.asyncio
async def test_hidden_and_temp_files_are_not_indexed(db, photos_dir):
    write_jpeg(photos_dir / ".stversions" / "old.jpg", seed=11)
    write_jpeg(photos_dir / "2024" / ".hidden.jpg", seed=14)
    visible = write_jpeg(photos_dir / "2024" / "new.jpg", seed=12)
    stats = await scan_directory()
    assert stats["total"] == 1 and stats["errors"] == 0
    assert await index_single_file(photos_dir / ".stversions" / "old.jpg") is None
    assert await index_single_file(photos_dir / "2024" / ".hidden.jpg") is None
    assert set(await _paths(db)) == {"2024/new.jpg"}
    assert visible.exists()


@pytest.mark.asyncio
async def test_already_indexed_hidden_photo_goes_through_removed_file_cleanup(db, photos_dir):
    """The live index has one .stversions photo (indexed by the old watcher).
    It is dropped exactly like a deleted file, even though it is still on
    disk, with its derived rows; a hash that also lives at a normal path
    only loses the hidden path."""
    hidden = write_jpeg(photos_dir / ".stversions" / "2026" / "P1~old.jpg", seed=15)
    dual = write_jpeg(photos_dir / "keep" / "a.jpg", seed=16)
    dual_hidden = photos_dir / ".stversions" / "a~old.jpg"
    shutil.copy2(dual, dual_hidden)
    fh_hidden, fh_dual = compute_file_hash(hidden), compute_file_hash(dual)
    async with db() as session:
        session.add_all([
            Photo(file_hash=fh_hidden, file_path=".stversions/2026/P1~old.jpg",
                  file_name="P1~old.jpg", file_size=hidden.stat().st_size),
            PhotoPath(file_hash=fh_hidden, file_path=".stversions/2026/P1~old.jpg"),
            PhotoHash(file_hash=fh_hidden, phash="0" * 16),
            Face(file_hash=fh_hidden, bbox_x=0, bbox_y=0, bbox_w=0, bbox_h=0, encoding=None),
            Caption(file_hash=fh_hidden, caption="old", model="m"),
            Tag(tag_id=1, name="tree"),
            PhotoTag(file_hash=fh_hidden, tag_id=1),
            # Primary path is the hidden copy: must move to the visible one.
            Photo(file_hash=fh_dual, file_path=".stversions/a~old.jpg", file_name="a.jpg",
                  file_size=dual.stat().st_size, is_favorite=True),
            PhotoPath(file_hash=fh_dual, file_path=".stversions/a~old.jpg"),
            PhotoPath(file_hash=fh_dual, file_path="keep/a.jpg"),
            Caption(file_hash=fh_dual, caption="kept", model="m"),
        ])
        await session.commit()

    await scan_directory(fast=True)

    async with db() as session:
        photos = {p.file_hash: p for p in (await session.execute(select(Photo))).scalars()}
        paths = (await session.execute(select(PhotoPath.file_path))).scalars().all()
        derived = {
            model.__tablename__: (await session.execute(
                select(model.file_hash).where(model.file_hash == fh_hidden))).all()
            for model in (PhotoHash, Face, Caption, PhotoTag)
        }
        dual_caption = await session.get(Caption, fh_dual)
    assert set(photos) == {fh_dual}
    assert photos[fh_dual].file_path == "keep/a.jpg"
    assert photos[fh_dual].is_favorite
    assert dual_caption.caption == "kept"
    assert sorted(paths) == ["keep/a.jpg"]
    assert all(rows == [] for rows in derived.values()), derived
    assert hidden.exists()  # files on disk are never touched


@pytest.mark.asyncio
async def test_symlinks_out_of_the_library_are_not_followed(db, photos_dir, tmp_path):
    outside = write_jpeg(tmp_path / "outside" / "secret.jpg", seed=17)
    inside = write_jpeg(photos_dir / "real" / "in.jpg", seed=18)
    (photos_dir / "links").mkdir()
    (photos_dir / "links" / "out.jpg").symlink_to(outside)
    (photos_dir / "links" / "in.jpg").symlink_to(inside)
    (photos_dir / "outdir").symlink_to(outside.parent, target_is_directory=True)
    stats = await scan_directory()
    assert stats["errors"] == 0
    assert set(await _paths(db)) == {"real/in.jpg", "links/in.jpg"}
    assert await index_single_file(photos_dir / "links" / "out.jpg") is None


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
