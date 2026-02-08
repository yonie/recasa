"""Google Motion Photo extraction service.

Google Motion Photos embed an MP4 video at the end of a JPEG file.
This service extracts the embedded video to a separate file so it
can be served for hover-to-play previews.
"""

import asyncio
import logging
from pathlib import Path

from sqlalchemy import select

from backend.app.config import settings
from backend.app.database import async_session
from backend.app.models import Photo

logger = logging.getLogger(__name__)

# Known markers that indicate the start of embedded MP4 data
MP4_SIGNATURES = [
    b"ftypmp4",
    b"ftypisom",
    b"ftypmp42",
    b"ftypavc1",
]

# XMP marker for Google Motion Photo offset
MOTION_PHOTO_OFFSET_MARKER = b"MotionPhoto"


def _extract_motion_photo_video(filepath: Path) -> Path | None:
    """Extract embedded MP4 video from a Google Motion Photo JPEG.

    Returns the path to the extracted video file, or None if extraction fails.
    """
    try:
        with open(filepath, "rb") as f:
            data = f.read()

        # Strategy 1: Look for the MP4 ftyp box header
        # The ftyp box starts with a 4-byte size followed by 'ftyp'
        mp4_offset = None
        for sig in MP4_SIGNATURES:
            # ftyp box: [4 bytes size][4 bytes 'ftyp'][brand bytes]
            # We look for 'ftyp' + brand
            idx = data.find(sig)
            if idx >= 4:
                # The box starts 4 bytes before 'ftyp'
                mp4_offset = idx - 4
                break

        if mp4_offset is None:
            return None

        # Verify it looks like an MP4 (should start with a valid box size)
        mp4_data = data[mp4_offset:]
        if len(mp4_data) < 8:
            return None

        # Extract the video
        video_dir = settings.data_dir / "motion_videos" / filepath.stem[:2]
        video_dir.mkdir(parents=True, exist_ok=True)

        video_filename = f"{filepath.stem}_motion.mp4"
        video_path = video_dir / video_filename

        with open(video_path, "wb") as vf:
            vf.write(mp4_data)

        return video_path

    except Exception:
        logger.exception("Error extracting motion photo from %s", filepath)
        return None


async def extract_motion_video(file_hash: str) -> bool:
    """Extract motion photo video for a photo if it's a Google Motion Photo."""
    async with async_session() as session:
        photo = await session.get(Photo, file_hash)
        if not photo:
            return False

        if not photo.motion_photo:
            return False

        # Skip if we already have a video path
        if photo.live_photo_video:
            return True

        filepath = settings.photos_dir / photo.file_path
        if not filepath.exists():
            return False

        video_path = await asyncio.to_thread(_extract_motion_photo_video, filepath)
        if video_path:
            # Store relative to data_dir since it's extracted data
            photo.live_photo_video = f"_motion/{filepath.stem[:2]}/{filepath.stem}_motion.mp4"
            await session.commit()
            logger.debug("Extracted motion video for %s", file_hash)
            return True

        return False


async def process_pending_motion_photos(batch_size: int | None = None) -> int:
    """Process all motion photos that haven't had their video extracted."""
    if batch_size is None:
        batch_size = settings.batch_size

    async with async_session() as session:
        result = await session.execute(
            select(Photo.file_hash)
            .where(Photo.motion_photo == True)  # noqa: E712
            .where(Photo.live_photo_video.is_(None))
            .limit(batch_size)
        )
        hashes = result.scalars().all()

    processed = 0
    for file_hash in hashes:
        if await extract_motion_video(file_hash):
            processed += 1

    if processed:
        logger.info("Extracted motion videos for %d photos", processed)
    return processed
