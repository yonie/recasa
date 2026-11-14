"""Google Motion Photo extraction service.

Google Motion Photos embed an MP4 video at the end of a JPEG file.
This service extracts the embedded video to a separate file so it
can be served for hover-to-play previews.
"""

import logging
import mmap
from pathlib import Path

from backend.app.config import settings
from backend.app.database import async_session
from backend.app.models import Photo
from backend.app.services.media_task import run_media_task

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

# photos.live_photo_video of a motion photo is "_motion/<name>", where <name>
# is relative to data_dir/motion_videos (a Live Photo's is a library path).
STORED_PREFIX = "_motion/"


def motion_videos_dir() -> Path:
    return settings.data_dir / "motion_videos"


def _video_name(file_hash: str) -> str:
    """Named by content hash: two motion photos with the same file name in
    different folders must not share (and overwrite) one video."""
    return f"{file_hash[:2]}/{file_hash}_motion.mp4"


def motion_video_path(file_hash: str, stored: str | None) -> Path | None:
    """The extracted video of a motion photo, or None if there is none.

    `stored` is the photo's live_photo_video. Videos extracted before the
    hash naming are named after the photo's file stem and stay readable
    under that stored name.
    """
    root = motion_videos_dir()
    candidates = [root / _video_name(file_hash)]
    if stored and stored.startswith(STORED_PREFIX):
        name = stored.removeprefix(STORED_PREFIX)
        if "/" in name and ".." not in Path(name).parts:
            candidates.append(root / name)
    return next((c for c in candidates if c.is_file()), None)


def _extract_motion_photo_video(filepath: Path, file_hash: str) -> Path | None:
    """Extract embedded MP4 video from a Google Motion Photo JPEG.

    Returns the path to the extracted video file, or None if extraction fails.
    """
    try:
        # Memory-mapped rather than read whole: searching a large JPEG does not
        # pull all of it into the process, only the video part is copied out.
        with open(filepath, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
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
        video_path = motion_videos_dir() / _video_name(file_hash)
        video_path.parent.mkdir(parents=True, exist_ok=True)

        with open(video_path, "wb") as vf:
            vf.write(mp4_data)

        return video_path

    except Exception as e:
        logger.warning("Skipping motion photo %s: %s", filepath, type(e).__name__)
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
        file_path = photo.file_path

    # Already extracted (the commit below did not happen last time): the
    # video is content-named, so it is this photo's.
    if motion_video_path(file_hash, None) is None:
        filepath = settings.photos_dir / file_path
        if not filepath.exists():
            return False
        if not await run_media_task(_extract_motion_photo_video, filepath, file_hash):
            return False

    async with async_session() as session:
        photo = await session.get(Photo, file_hash)
        if not photo:
            return False
        # Store relative to data_dir since it's extracted data
        photo.live_photo_video = STORED_PREFIX + _video_name(file_hash)
        await session.commit()
    logger.debug("Extracted motion video for %s", file_hash)
    return True
