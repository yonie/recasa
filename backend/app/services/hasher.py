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

# Hamming distance threshold for considering photos as duplicates
DUPLICATE_THRESHOLD = 8


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
    except Exception:
        logger.exception("Error computing hashes for %s", filepath)
        return {}


async def compute_hashes(file_hash: str) -> bool:
    """Compute perceptual hashes for a photo and store them."""
    async with async_session() as session:
        photo = await session.get(Photo, file_hash)
        if not photo:
            return False

        if photo.perceptual_hashed:
            return True

        filepath = settings.photos_dir / photo.file_path
        if not filepath.exists():
            return False

        hashes = await asyncio.to_thread(_compute_perceptual_hashes, filepath)
        if not hashes:
            return False

        # Upsert hash record
        existing = await session.get(PhotoHash, file_hash)
        if existing:
            existing.phash = hashes.get("phash")
            existing.ahash = hashes.get("ahash")
            existing.dhash = hashes.get("dhash")
        else:
            session.add(PhotoHash(file_hash=file_hash, **hashes))

        photo.perceptual_hashed = True
        await session.commit()

        logger.debug("Computed perceptual hashes for %s", file_hash)
        return True


async def find_duplicates() -> list[list[str]]:
    """Find groups of duplicate photos based on perceptual hash similarity.

    Returns list of groups, where each group is a list of file_hashes.
    """
    async with async_session() as session:
        result = await session.execute(select(PhotoHash))
        all_hashes = result.scalars().all()

    if not all_hashes:
        return []

    # Build groups using union-find approach
    groups: dict[str, set[str]] = {}
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Compare all pairs (O(n^2) - could be optimized with LSH for large libraries)
    for i, h1 in enumerate(all_hashes):
        if not h1.phash:
            continue
        for h2 in all_hashes[i + 1 :]:
            if not h2.phash:
                continue

            try:
                distance = imagehash.hex_to_hash(h1.phash) - imagehash.hex_to_hash(h2.phash)
                if distance <= DUPLICATE_THRESHOLD:
                    union(h1.file_hash, h2.file_hash)
            except Exception:
                continue

    # Collect groups
    group_map: dict[str, list[str]] = {}
    for h in all_hashes:
        root = find(h.file_hash)
        if root not in group_map:
            group_map[root] = []
        group_map[root].append(h.file_hash)

    # Only return groups with 2+ members
    duplicate_groups = [g for g in group_map.values() if len(g) > 1]

    # Store in database
    async with async_session() as session:
        # Clear existing duplicate groups
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


async def process_pending_hashes(batch_size: int | None = None) -> int:
    """Process all photos that haven't been perceptually hashed yet."""
    if batch_size is None:
        batch_size = settings.batch_size

    async with async_session() as session:
        result = await session.execute(
            select(Photo.file_hash)
            .where(Photo.perceptual_hashed == False)  # noqa: E712
            .limit(batch_size)
        )
        hashes = result.scalars().all()

    processed = 0
    for file_hash in hashes:
        if await compute_hashes(file_hash):
            processed += 1

    if processed:
        logger.info("Computed perceptual hashes for %d photos", processed)
    return processed
