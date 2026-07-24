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


def _display_rotation(stream) -> int:
    """Display rotation in degrees, normalized to 0/90/180/270.

    PyAV 13 exposes the display matrix as a float under the DISPLAYMATRIX key
    of stream.side_data (dict). ffmpeg's convention is a counter-clockwise
    angle, e.g. -90 for a clip that must be turned 90 clockwise to view.
    """
    try:
        sd = stream.side_data
        if sd and "DISPLAYMATRIX" in sd:
            return int(round(float(sd["DISPLAYMATRIX"]))) % 360
    except Exception:
        pass
    return 0


def extract_poster_frame(filepath: Path):
    """Decode the first video frame as an upright PIL RGB Image (or None).

    Frames decode in storage orientation; we apply the stream's display
    rotation so the poster matches what a player shows.
    """
    try:
        import av

        with av.open(str(filepath)) as container:
            stream = next((s for s in container.streams if s.type == "video"), None)
            if stream is None:
                return None
            rotation = _display_rotation(stream)
            stream.codec_context.skip_frame = "NONKEY"
            for frame in container.decode(stream):
                img = frame.to_image().convert("RGB")
                if rotation:
                    # side_data angle is counter-clockwise; PIL rotate() is
                    # also counter-clockwise, so rotating by the same angle
                    # brings the stored frame upright.
                    img = img.rotate(rotation, expand=True)
                return img
    except Exception as e:
        logger.warning("Could not extract poster from %s: %s", filepath, type(e).__name__)
    return None
