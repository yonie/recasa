"""Generate photo collage grids."""

import random
from io import BytesIO

import numpy as np
from PIL import Image

from backend.app.services.thumbnail import _get_thumbnail_path


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _select_diverse(
    file_hashes: list[str],
    phashes: list[str | None],
    needed: int,
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
        return list(file_hashes)

    # Start from a random photo (seed-controlled via caller's random.seed)
    start = random.randint(0, n - 1)
    selected: list[int] = [start]
    selected_ph: list[int | None] = [ph_ints[start]]
    remaining = set(range(n)) - {start}

    while len(selected) < needed and remaining:
        best_idx = -1
        best_min_dist = -1

        for idx in remaining:
            ph = ph_ints[idx]
            if ph is None:
                min_dist = 16  # moderate default for missing phash
            else:
                min_dist = 64  # max possible hamming distance
                for sp in selected_ph:
                    if sp is not None:
                        min_dist = min(min_dist, _hamming(ph, sp))
                    else:
                        min_dist = min(min_dist, 16)

            if min_dist > best_min_dist:
                best_min_dist = min_dist
                best_idx = idx

        if best_idx < 0:
            break

        selected.append(best_idx)
        selected_ph.append(ph_ints[best_idx])
        remaining.discard(best_idx)

    return [file_hashes[i] for i in selected]


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
                img = Image.open(path)
                grey = img.convert("L")
                brightness = float(np.array(grey).mean())
                img.close()
            except Exception:
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
    dates: list = None,  # kept for API compat, unused
    seed: int = 0,
) -> bytes | None:
    """Generate a square collage from photo thumbnails."""
    random.seed(seed)

    if not file_hashes:
        return None

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
    selected = _select_diverse(file_hashes, phashes, needed)

    if not selected:
        return None

    # Shrink grid if not enough distinct photos
    while len(selected) < cols * cols and cols > 1:
        cols -= 1

    selected = selected[: cols * cols]

    # Scatter so adjacent tiles contrast
    selected = _scatter_grid(selected)

    # Build the collage
    tile_size = output_size // cols
    images: list[Image.Image] = []
    for fh in selected:
        path = _get_thumbnail_path(fh, 600)
        if not path.exists():
            path = _get_thumbnail_path(fh, 200)
        if not path.exists():
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
        except Exception:
            continue

    if not images:
        return None

    canvas = Image.new("RGB", (cols * tile_size, cols * tile_size), (255, 255, 255))
    for i, img in enumerate(images):
        x = (i % cols) * tile_size
        y = (i // cols) * tile_size
        canvas.paste(img, (x, y))

    buf = BytesIO()
    canvas.save(buf, format="JPEG", quality=90)
    return buf.getvalue()
