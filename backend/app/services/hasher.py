"""Perceptual hashing service for duplicate detection."""

import asyncio
import logging
from pathlib import Path

import imagehash
from PIL import Image

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import settings
from backend.app.database import async_session
from backend.app.models import Photo, PhotoHash, DuplicateGroup, DuplicateMember

logger = logging.getLogger(__name__)

# Hamming distance threshold for considering photos as duplicates.
# 0 = identical, 1-3 = same photo different resolution/compression, 4-6 = similar with edits.
DUPLICATE_THRESHOLD = 4


def _compute_perceptual_hashes(filepath: Path) -> dict:
    """Compute perceptual hashes for a photo."""
    try:
        with Image.open(filepath) as img:
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            return {
                "phash": str(imagehash.phash(img)),
                "ahash": str(imagehash.average_hash(img)),
                "dhash": str(imagehash.dhash(img)),
            }
    except Exception as e:
        logger.warning("Skipping hash for %s: %s", filepath, type(e).__name__)
        return {}


async def compute_hashes(file_hash: str) -> bool:
    """Compute perceptual hashes for a photo and store them."""
    async with async_session() as session:
        photo = await session.get(Photo, file_hash)
        if not photo:
            return False

        # Check if hash already exists
        existing = await session.get(PhotoHash, file_hash)
        if existing:
            return True

        filepath = settings.photos_dir / photo.file_path
        if not filepath.exists():
            return False

        hashes = await asyncio.to_thread(_compute_perceptual_hashes, filepath)
        if not hashes:
            return False

        session.add(PhotoHash(file_hash=file_hash, **hashes))
        await session.commit()

        logger.debug("Computed perceptual hashes for %s", file_hash)
        return True


def _find_duplicate_groups(
    file_hashes: list[str], phash_hexes: list[str], threshold: int
) -> list[list[str]]:
    """CPU-bound duplicate detection using numpy-vectorized hamming distance.

    Compares all pairs of perceptual hashes and groups photos within the
    hamming distance threshold using union-find.
    """
    import numpy as np

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

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Vectorized popcount for uint64 arrays (Hamming weight via bit manipulation)
    def _popcount64(arr: np.ndarray) -> np.ndarray:
        c1 = np.uint64(0x5555555555555555)
        c2 = np.uint64(0x3333333333333333)
        c4 = np.uint64(0x0F0F0F0F0F0F0F0F)
        cm = np.uint64(0x0101010101010101)
        arr = arr - ((arr >> np.uint64(1)) & c1)
        arr = (arr & c2) + ((arr >> np.uint64(2)) & c2)
        arr = (arr + (arr >> np.uint64(4))) & c4
        return (arr * cm) >> np.uint64(56)

    # For each photo, vectorized comparison against all subsequent photos
    for i in range(n - 1):
        xor = phash_ints[i + 1 :] ^ phash_ints[i]
        distances = _popcount64(xor)
        matches = np.where(distances <= threshold)[0]
        for j_offset in matches:
            union(i, int(i + 1 + j_offset))

    # Collect groups with 2+ members
    group_map: dict[int, list[str]] = {}
    for i in range(n):
        root = find(i)
        group_map.setdefault(root, []).append(file_hashes[i])

    return [g for g in group_map.values() if len(g) > 1]


async def find_duplicates() -> list[list[str]]:
    """Find groups of duplicate photos based on perceptual hash similarity.

    Uses numpy-vectorized hamming distance for fast comparison of all pairs.
    Returns list of groups, where each group is a list of file_hashes.
    """
    async with async_session() as session:
        result = await session.execute(
            select(PhotoHash).where(PhotoHash.phash.is_not(None))
        )
        all_hashes = result.scalars().all()

    if len(all_hashes) < 2:
        return []

    file_hashes = [h.file_hash for h in all_hashes]
    phash_hexes = [h.phash for h in all_hashes]

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
