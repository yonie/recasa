"""Video metadata and poster-frame extraction (via PyAV / ffmpeg).

v1 uses the first decodable frame as the poster. Picking a good keyframe
instead of frame 0 is deliberately deferred to a later release.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_video_metadata(filepath: Path) -> dict:
    """Return {duration, width, height} for a video, or {} if unreadable."""
    try:
        import av

        with av.open(str(filepath)) as container:
            stream = next((s for s in container.streams if s.type == "video"), None)
            if stream is None:
                return {}

            duration = None
            if container.duration is not None:
                duration = float(container.duration) / av.time_base
            elif stream.duration is not None and stream.time_base is not None:
                duration = float(stream.duration * stream.time_base)

            width = stream.codec_context.width or None
            height = stream.codec_context.height or None
            return {"duration": duration, "width": width, "height": height}
    except Exception as e:
        logger.warning("Could not read video metadata for %s: %s", filepath, type(e).__name__)
        return {}


def extract_poster_frame(filepath: Path):
    """Decode the first video frame and return it as a PIL RGB Image (or None).

    Note: display rotation is not applied — PyAV 13 doesn't expose the
    rotation/display-matrix side data at the Python level and no ffmpeg CLI is
    available to autorotate, so a small number of posters (rotated recordings)
    render sideways. Playback in the browser is unaffected (it honors the
    rotation). Tracked as a follow-up.
    """
    try:
        import av

        with av.open(str(filepath)) as container:
            stream = next((s for s in container.streams if s.type == "video"), None)
            if stream is None:
                return None
            stream.codec_context.skip_frame = "NONKEY"
            for frame in container.decode(stream):
                return frame.to_image().convert("RGB")
    except Exception as e:
        logger.warning("Could not extract poster from %s: %s", filepath, type(e).__name__)
    return None
