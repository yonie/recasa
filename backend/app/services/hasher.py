"""Perceptual hashing service for duplicate detection."""

import asyncio
import hashlib
import logging
from pathlib import Path

import imagehash
import numpy as np
from sqlalchemy import select

from backend.app.config import settings
from backend.app.database import async_session
from backend.app.exceptions import PermanentStageError
from backend.app.models import DuplicateGroup, DuplicateMember, Photo, PhotoHash
from backend.app.services.image_loader import PermanentReadError, open_image_cm

logger = logging.getLogger(__name__)

# Hamming distance threshold for considering photos as duplicates.
# 0 = identical, 1-3 = same photo different resolution/compression, 4-6 = similar with edits.
DUPLICATE_THRESHOLD = 4

# Rows compared per step in _find_duplicate_groups. Bounds the temporary
# distance matrix to BLOCK x library size (64 x 40k bytes, plus the XOR).
_COMPARE_BLOCK = 64


def _compute_perceptual_hashes(filepath: Path) -> dict:
    """Compute perceptual hashes for a photo.

    Raises PermanentStageError for unreadable/corrupted files so the worker
    records the failure instead of re-queueing the photo forever.
    """
    try:
        with open_image_cm(filepath) as img:
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            # Each imagehash function starts with convert("L"); doing it once
            # here gives them the very same grayscale pixels at a third of the
            # cost of three full-size conversions.
            gray = img.convert("L")

            return {
                "phash": str(imagehash.phash(gray)),
                "ahash": str(imagehash.average_hash(gray)),
                "dhash": str(imagehash.dhash(gray)),
            }
    except PermanentReadError as e:
        raise PermanentStageError(str(e)) from e
    except Exception as e:
        logger.warning("Skipping hash for %s: %s", filepath, type(e).__name__)
        raise PermanentStageError(f"cannot read image ({type(e).__name__})") from e


async def compute_hashes(file_hash: str) -> bool:
    """Compute perceptual hashes for a photo and store them."""
    async with async_session() as session:
        photo = await session.get(Photo, file_hash)
        if not photo:
            return False
        if await session.get(PhotoHash, file_hash):
            return True
        file_path = photo.file_path

    filepath = settings.photos_dir / file_path
    if not filepath.exists():
        raise PermanentStageError("file not found on disk")

    hashes = await asyncio.to_thread(_compute_perceptual_hashes, filepath)
    if not hashes:
        raise PermanentStageError("no hashes could be computed")

    async with async_session() as session:
        session.add(PhotoHash(file_hash=file_hash, **hashes))
        await session.commit()

    logger.debug("Computed perceptual hashes for %s", file_hash)
    return True


def _popcount64(arr: np.ndarray) -> np.ndarray:
    """Per-element set-bit count of a uint64 array (numpy < 2 fallback)."""
    c1 = np.uint64(0x5555555555555555)
    c2 = np.uint64(0x3333333333333333)
    c4 = np.uint64(0x0F0F0F0F0F0F0F0F)
    cm = np.uint64(0x0101010101010101)
    arr = arr - ((arr >> np.uint64(1)) & c1)
    arr = (arr & c2) + ((arr >> np.uint64(2)) & c2)
    arr = (arr + (arr >> np.uint64(4))) & c4
    return (arr * cm) >> np.uint64(56)


_popcount = getattr(np, "bitwise_count", _popcount64)


def _find_duplicate_groups(
    file_hashes: list[str], phash_hexes: list[str], threshold: int
) -> list[list[str]]:
    """Group photos whose perceptual hashes are within `threshold` bits.

    Every pair is compared (vectorized, a block of rows at a time) and pairs
    within the threshold are joined with union-find. Groups come out ordered
    by their first member's position in the input, members in input order,
    so the result depends only on which pairs match.
    """
    n = len(file_hashes)
    if n < 2:
        return []

    phash_ints = np.array([int(h, 16) for h in phash_hexes], dtype=np.uint64)

    # Union-find with path compression
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for start in range(0, n - 1, _COMPARE_BLOCK):
        block = phash_ints[start : start + _COMPARE_BLOCK]
        later = phash_ints[start + 1 :]
        distances = _popcount(block[:, None] ^ later[None, :])
        rows, cols = np.nonzero(distances <= threshold)
        for r, c in zip(rows.tolist(), cols.tolist(), strict=True):
            i, j = start + r, start + 1 + c
            if j <= i:
                continue  # each pair once, and never a photo with itself
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[ri] = rj

    # Collect groups with 2+ members
    group_map: dict[int, list[str]] = {}
    for i in range(n):
        group_map.setdefault(find(i), []).append(file_hashes[i])

    return [g for g in group_map.values() if len(g) > 1]


def _phash_query():
    return select(PhotoHash.file_hash, PhotoHash.phash).where(PhotoHash.phash.is_not(None))


async def phash_signature() -> bytes:
    """Digest of exactly the input find_duplicates would read.

    Equal digests mean a rerun would store identical groups, which lets the
    batch worker skip the all-pairs comparison when nothing was hashed or
    removed since its last run.
    """
    digest = hashlib.blake2b(digest_size=16)
    async with async_session() as session:
        for file_hash, phash in await session.execute(_phash_query()):
            digest.update(f"{file_hash}:{phash};".encode())
    return digest.digest()


async def find_duplicates() -> list[list[str]]:
    """Find groups of duplicate photos based on perceptual hash similarity.

    Uses numpy-vectorized hamming distance for fast comparison of all pairs.
    Returns list of groups, where each group is a list of file_hashes.
    """
    async with async_session() as session:
        rows = (await session.execute(_phash_query())).all()

    if len(rows) < 2:
        return []

    file_hashes = [fh for fh, _ in rows]
    phash_hexes = [ph for _, ph in rows]

    logger.info("Finding duplicates among %d photos...", len(file_hashes))

    # Run CPU-bound comparison in a thread to avoid blocking the event loop
    duplicate_groups = await asyncio.to_thread(
        _find_duplicate_groups, file_hashes, phash_hexes, DUPLICATE_THRESHOLD
    )

    # Store in database
    async with async_session() as session:
        await session.execute(DuplicateMember.__table__.delete())
        await session.execute(DuplicateGroup.__table__.delete())

        for group_hashes in duplicate_groups:
            group = DuplicateGroup()
            session.add(group)
            await session.flush()

            for fh in group_hashes:
                session.add(DuplicateMember(group_id=group.group_id, file_hash=fh))

        await session.commit()

    logger.info("Found %d duplicate groups", len(duplicate_groups))
    return duplicate_groups
