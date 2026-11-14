"""Thumbnails and perceptual hashes: same outputs, cheaper to produce."""

import random
from pathlib import Path

import imagehash
import numpy as np
import pytest
from PIL import Image

from backend.app.services import hasher, thumbnail
from backend.app.services.hasher import _compute_perceptual_hashes, _find_duplicate_groups
from backend.app.services.thumbnail import (
    _generate_thumbnail,
    existing_thumb_hashes,
    get_thumbnail_path,
    thumb_exists,
)

from .helpers import h, write_jpeg


def _reference_groups(file_hashes, phash_hexes, threshold):
    """The pre-rewrite algorithm: one row against all later rows, union-find."""
    n = len(file_hashes)
    if n < 2:
        return []
    ints = np.array([int(x, 16) for x in phash_hexes], dtype=np.uint64)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n - 1):
        d = hasher._popcount64(ints[i + 1 :] ^ ints[i])
        for j in np.where(d <= threshold)[0]:
            ra, rb = find(i), find(int(i + 1 + j))
            if ra != rb:
                parent[ra] = rb
    groups: dict[int, list[str]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(file_hashes[i])
    return [g for g in groups.values() if len(g) > 1]


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_duplicate_groups_match_reference(seed):
    rnd = random.Random(seed)
    base = [rnd.getrandbits(64) for _ in range(40)]
    values = []
    for _ in range(700):
        v = rnd.choice(base) if rnd.random() < 0.5 else rnd.getrandbits(64)
        for _ in range(rnd.randrange(7)):  # flip a few bits: near the threshold
            v ^= 1 << rnd.randrange(64)
        values.append(v)
    hexes = [f"{v:016x}" for v in values]
    names = [h(i) for i in range(len(values))]
    expected = _reference_groups(names, hexes, 4)
    assert expected  # the data does contain duplicates
    assert _find_duplicate_groups(names, hexes, 4) == expected


def test_popcount_paths_agree():
    arr = np.array([0, 1, 2**64 - 1, 0xF0F0, 2**63], dtype=np.uint64)
    assert hasher._popcount64(arr).tolist() == [0, 1, 64, 8, 1]
    assert np.asarray(hasher._popcount(arr)).astype(int).tolist() == [0, 1, 64, 8, 1]


@pytest.mark.parametrize("mode", ["RGB", "RGBA", "L", "P", "CMYK"])
def test_perceptual_hashes_unchanged(tmp_path: Path, mode):
    rnd = random.Random(7)
    img = Image.new("RGB", (97, 61))
    img.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
                 for _ in range(97 * 61)])
    img = img.convert(mode)
    path = tmp_path / ("x.tiff" if mode == "CMYK" else "x.png")
    img.save(path)

    with Image.open(path) as ref:
        if ref.mode not in ("RGB", "L"):
            ref = ref.convert("RGB")
        expected = {
            "phash": str(imagehash.phash(ref)),
            "ahash": str(imagehash.average_hash(ref)),
            "dhash": str(imagehash.dhash(ref)),
        }
    assert _compute_perceptual_hashes(path) == expected


def test_thumbnails_all_sizes_marker_last(db, photos_dir, monkeypatch):
    src = write_jpeg(photos_dir / "big.jpg", seed=1, size=(1600, 900))
    order: list[int] = []
    real_save = thumbnail._save_atomic

    def spy(img, path):
        order.append(img.size)
        real_save(img, path)

    monkeypatch.setattr(thumbnail, "_save_atomic", spy)
    fh = h(1)
    _generate_thumbnail(src, fh, [200, 600, 1200])
    assert order == [(1200, 675), (600, 338), (200, 113)]
    assert thumb_exists(fh)
    assert existing_thumb_hashes() == {fh}
    assert get_thumbnail_path(fh, 700).name == f"{fh}_1200.webp"
    assert get_thumbnail_path(fh, 5000).name == f"{fh}_1200.webp"
    leftovers = [p for p in thumbnail._get_thumbnail_path(fh, 200).parent.iterdir()
                 if p.name.endswith(".tmp")]
    assert leftovers == []


def test_thumbnails_respect_exif_orientation(db, photos_dir):
    img = Image.new("RGB", (400, 200), (200, 10, 10))
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 CW to display
    path = photos_dir / "rot.jpg"
    img.save(path, "JPEG", exif=exif.tobytes())
    _generate_thumbnail(path, h(2), [200])
    with Image.open(thumbnail._get_thumbnail_path(h(2), 200)) as t:
        assert t.size == (100, 200)


def test_existing_thumbnails_are_kept(db, photos_dir):
    src = write_jpeg(photos_dir / "k.jpg", seed=3, size=(800, 800))
    fh = h(3)
    marker = thumbnail._get_thumbnail_path(fh, 600)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_bytes(b"keep")
    _generate_thumbnail(src, fh, [200, 600])
    assert marker.read_bytes() == b"keep"
    assert thumb_exists(fh)


def test_unreadable_image_is_a_permanent_failure(tmp_path: Path):
    from backend.app.exceptions import PermanentStageError

    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"\xff\xd8\xff" + b"\0" * 4000)
    with pytest.raises(PermanentStageError, match="cannot read image"):
        _generate_thumbnail(bad, h(4), [200])
    with pytest.raises(PermanentStageError, match="cannot read image"):
        _compute_perceptual_hashes(bad)
