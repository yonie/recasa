"""Generate photo collage grids."""

import random
from io import BytesIO

import numpy as np
from PIL import Image

from backend.app.services.thumbnail import _get_thumbnail_path


def _hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


# Photos within this phash distance are the same shot (mirrors
# DUPLICATE_THRESHOLD in the hasher service) — never show both in one collage.
DUPLICATE_HAMMING = 4


def _select_diverse(
    file_hashes: list[str],
    phashes: list[str | None],
    needed: int,
    rng: random.Random,
) -> list[str]:
    """Select visually diverse photos using greedy max-distance phash picking.

    Each subsequent photo is chosen to maximize its minimum phash hamming
    distance from all already-selected photos. This naturally deduplicates
    visually similar shots without arbitrary time-based grouping.
    """
    n = len(file_hashes)
    if n == 0:
        return []

    # Parse phashes to ints
    ph_ints: list[int | None] = []
    for ph in phashes:
        try:
            ph_ints.append(int(ph, 16) if ph else None)
        except (ValueError, TypeError):
            ph_ints.append(None)

    if n <= needed:
        # Small pool: keep order, but still drop near-duplicate shots.
        kept: list[int] = []
        kept_ph: list[int] = []
        for i in range(n):
            ph = ph_ints[i]
            if ph is not None and any(_hamming(ph, kp) <= DUPLICATE_HAMMING for kp in kept_ph):
                continue
            kept.append(i)
            if ph is not None:
                kept_ph.append(ph)
        return [file_hashes[i] for i in kept]

    # Start from a random photo (seed-controlled by the caller's rng)
    start = rng.randint(0, n - 1)
    if all(ph is None or 0 <= ph < 1 << 64 for ph in ph_ints):
        selected = _greedy_farthest_numpy(ph_ints, start, needed)
    else:
        selected = _greedy_farthest(ph_ints, start, needed)
    return [file_hashes[i] for i in selected]


# Distance assumed between a photo and anything when either has no phash
MISSING_PHASH_DISTANCE = 16


def _greedy_farthest(ph_ints: list[int | None], start: int, needed: int) -> list[int]:
    """Reference greedy pick, for phashes that do not fit 64 bits.

    Repeatedly takes the candidate whose smallest distance to the picks so
    far is largest (lowest index on ties), stopping early once even the best
    candidate is a near-duplicate of a pick.
    """
    n = len(ph_ints)
    selected: list[int] = [start]
    selected_ph: list[int | None] = [ph_ints[start]]
    remaining = set(range(n)) - {start}

    while len(selected) < needed and remaining:
        best_idx = -1
        best_min_dist = -1

        for idx in sorted(remaining):
            ph = ph_ints[idx]
            if ph is None:
                min_dist = MISSING_PHASH_DISTANCE
            else:
                min_dist = 64  # max possible hamming distance
                for sp in selected_ph:
                    if sp is not None:
                        min_dist = min(min_dist, _hamming(ph, sp))
                    else:
                        min_dist = min(min_dist, MISSING_PHASH_DISTANCE)

            if min_dist > best_min_dist:
                best_min_dist = min_dist
                best_idx = idx

        # If the most-different candidate left is still a near-duplicate of a
        # selected photo, every remaining photo is a dupe: stop and let the
        # caller shrink the grid rather than show the same shot twice.
        if best_idx < 0 or best_min_dist <= DUPLICATE_HAMMING:
            break

        selected.append(best_idx)
        selected_ph.append(ph_ints[best_idx])
        remaining.discard(best_idx)

    return selected


# Set-bit count of every byte value, for popcount on numpy versions that
# lack np.bitwise_count.
_BYTE_POPCOUNT = np.array([i.bit_count() for i in range(256)], dtype=np.uint8)


def _popcount64(values: np.ndarray) -> np.ndarray:
    return _BYTE_POPCOUNT[values.view(np.uint8)].reshape(-1, 8).sum(axis=1, dtype=np.int64)


def _greedy_farthest_numpy(ph_ints: list[int | None], start: int, needed: int) -> list[int]:
    """The same pick as _greedy_farthest, vectorised.

    The Python version recomputed every candidate's distance to every pick
    on each round: for a 17k-photo tag and a 6x6 grid that is millions of
    Python-level operations, seconds on the Pi. Here each candidate keeps
    its running minimum distance, updated once per new pick.
    """
    n = len(ph_ints)
    has_ph = np.array([ph is not None for ph in ph_ints])
    phs = np.array([ph or 0 for ph in ph_ints], dtype=np.uint64)

    # Without a phash a candidate is always MISSING_PHASH_DISTANCE away.
    min_dist = np.where(has_ph, 64, MISSING_PHASH_DISTANCE).astype(np.int64)
    available = np.ones(n, dtype=bool)

    def take(idx: int) -> None:
        available[idx] = False
        if has_ph[idx]:
            dist = _popcount64(phs ^ phs[idx])
        else:
            dist = np.full(n, MISSING_PHASH_DISTANCE, dtype=np.int64)
        np.minimum(min_dist, np.where(has_ph, dist, MISSING_PHASH_DISTANCE), out=min_dist)

    selected = [start]
    take(start)
    while len(selected) < needed and available.any():
        # Lowest index among the farthest, as the reference loop picks.
        best_idx = int(np.argmax(np.where(available, min_dist, -1)))
        if min_dist[best_idx] <= DUPLICATE_HAMMING:
            break
        selected.append(best_idx)
        take(best_idx)
    return selected


def _scatter_grid(hashes: list[str]) -> list[str]:
    """Arrange photos so visually similar ones aren't adjacent.

    Sorts by brightness then interleaves from opposite ends so
    dark and light photos alternate across the grid.
    """
    items: list[tuple[str, float]] = []
    for fh in hashes:
        path = _get_thumbnail_path(fh, 600)
        if not path.exists():
            path = _get_thumbnail_path(fh, 200)
        brightness = 128.0
        if path.exists():
            try:
                with Image.open(path) as img:
                    brightness = float(np.array(img.convert("L")).mean())
            except Exception:  # noqa: BLE001, S110 - unreadable tile keeps the mid-grey default
                pass
        items.append((fh, brightness))

    items.sort(key=lambda x: x[1])

    # Interleave from opposite ends
    result: list[str] = []
    lo, hi = 0, len(items) - 1
    toggle = True
    while lo <= hi:
        if toggle:
            result.append(items[lo][0])
            lo += 1
        else:
            result.append(items[hi][0])
            hi -= 1
        toggle = not toggle

    return result


def generate_collage(
    file_hashes: list[str],
    phashes: list[str | None],
    grid: int = 0,
    output_size: int = 1400,
    seed: int = 0,
) -> bytes | None:
    """Generate a square collage from photo thumbnails."""
    return render_collage(file_hashes, phashes, grid, output_size, seed)[0]


def render_collage(
    file_hashes: list[str],
    phashes: list[str | None],
    grid: int = 0,
    output_size: int = 1400,
    seed: int = 0,
) -> tuple[bytes | None, bool]:
    """Generate a square collage; also say whether every chosen tile drew.

    The same inputs and seed always give the same picture, as long as the
    chosen photos' thumbnails exist (thumbnails never change once written).
    The second value is False when a tile was skipped for a missing or
    unreadable thumbnail, so the picture may still change: callers must not
    cache that one.

    The random generator is private to the call: collages render in worker
    threads, and seeding the shared module-level one let two concurrent
    renders disturb each other.
    """
    rng = random.Random(seed)

    if not file_hashes:
        return None, True

    n = len(file_hashes)

    # Determine grid size
    if grid >= 2:
        cols = min(grid, 6)
    else:
        if n >= 36:
            cols = 6
        elif n >= 25:
            cols = 5
        elif n >= 16:
            cols = 4
        elif n >= 9:
            cols = 3
        elif n >= 4:
            cols = 2
        else:
            cols = 1

    needed = cols * cols

    # Select diverse photos (greedy max phash distance)
    selected = _select_diverse(file_hashes, phashes, needed, rng)

    if not selected:
        return None, True

    # Shrink grid if not enough distinct photos
    while len(selected) < cols * cols and cols > 1:
        cols -= 1

    selected = selected[: cols * cols]

    # Scatter so adjacent tiles contrast
    selected = _scatter_grid(selected)

    # Build the collage
    tile_size = output_size // cols
    images: list[Image.Image] = []
    complete = True
    for fh in selected:
        path = _get_thumbnail_path(fh, 600)
        if not path.exists():
            path = _get_thumbnail_path(fh, 200)
        if not path.exists():
            complete = False
            continue
        try:
            img = Image.open(path)
            w, h = img.size
            side = min(w, h)
            left = (w - side) // 2
            top = (h - side) // 2
            img = img.crop((left, top, left + side, top + side))
            img = img.resize((tile_size, tile_size), Image.LANCZOS)
            images.append(img)
        except Exception:  # noqa: BLE001 - skip a tile that will not decode
            complete = False
            continue

    if not images:
        return None, complete

    canvas = Image.new("RGB", (cols * tile_size, cols * tile_size), (255, 255, 255))
    for i, img in enumerate(images):
        x = (i % cols) * tile_size
        y = (i // cols) * tile_size
        canvas.paste(img, (x, y))

    buf = BytesIO()
    canvas.save(buf, format="JPEG", quality=90)
    return buf.getvalue(), complete
