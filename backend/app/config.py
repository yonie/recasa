import os
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings, loaded from environment variables."""

    # Directories
    photos_dir: Path = Path("/photos")
    data_dir: Path = Path("/data")

    # Database
    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.data_dir / 'db' / 'recasa.db'}"

    # Thumbnails
    @property
    def thumbnails_dir(self) -> Path:
        return self.data_dir / "thumbs"

    thumbnail_sizes: list[int] = [200, 600, 1200]

    # Full-view previews for formats browsers can't decode (RAW). Rendered
    # on demand and cached; see services/preview.py.
    @property
    def previews_dir(self) -> Path:
        return self.data_dir / "previews"

    # Long-edge cap for rendered previews. 0 = native resolution, matching how
    # JPEG originals are served (the viewer supports pinch-zoom, so downscaling
    # would make RAW softer than everything else).
    preview_max_dimension: int = 0

    # Concurrent preview renders. A RAW decode is ~0.5s of CPU, and the viewer
    # prefetches neighbours, so this has to be bounded or previews starve the
    # API and the processing pipeline. Cache hits bypass it entirely.
    preview_concurrency: int = 2

    # Ollama
    ollama_url: str = "http://ollama:11434"
    ollama_model: str = "qwen3-vl:30b-a3b-instruct"
    # How long Ollama keeps the model loaded after a caption request. Sent per
    # request so it overrides the server default: a backlog stays warm, but the
    # GPU is freed an hour after the last photo.
    ollama_keep_alive: str = "1h"

    # Processing stages that can be switched off. EXIF, thumbnails, motion
    # photos and hashing always run: timeline order, every grid and duplicate
    # detection depend on them (see ignored_stage_switches below).
    ENABLE_GEOCODING: bool = True
    ENABLE_FACE_DETECTION: bool = False
    ENABLE_CAPTIONING: bool = False

    # Periodic rescan interval in seconds (0 disables). Needed because inotify
    # events don't cross Docker bind mounts on Windows/macOS hosts, so the
    # native file watcher never fires there. Sweeps stat every file, which is
    # slow on bind mounts — don't set this aggressively low on large libraries.
    watch_interval: int = 300

    # Maximum number of photos to process concurrently (limits memory usage)
    # Each concurrent photo uses memory for image loading, thumbnails, face detection, etc.
    # Recommended: 2-4 for systems with limited RAM, 4-8 for systems with more RAM
    max_concurrent: int = 4

    # Supported file extensions
    photo_extensions: set[str] = {
        ".jpg", ".jpeg", ".png", ".webp",
        ".heic", ".heif",
        ".tiff", ".tif", ".bmp",
        ".orf",  # Olympus RAW Format
    }

    # RAW formats (decoded via rawpy, not natively readable by PIL)
    raw_extensions: set[str] = {".orf"}
    video_extensions: set[str] = {
        ".mp4", ".mov", ".avi", ".mkv",
    }

    # Log level
    log_level: str = "info"

    model_config = {"env_prefix": "", "case_sensitive": False}


settings = Settings()


# Older compose files and .env templates carried switches for the stages that
# always run. Nothing ever read them, so a "false" there silently did nothing.
_ALWAYS_ON_STAGE_SWITCHES = (
    "ENABLE_EXIF_EXTRACTION",
    "ENABLE_THUMBNAILS",
    "ENABLE_MOTION_PHOTOS",
    "ENABLE_HASHING",
)


def ignored_stage_switches() -> list[str]:
    """Always-on stage switches that are set to a false value in the environment.

    Used to warn at startup instead of pretending the stage was turned off.
    """
    falsy = {"0", "false", "no", "off"}
    return [
        name for name in _ALWAYS_ON_STAGE_SWITCHES
        if os.environ.get(name, "").strip().lower() in falsy
    ]
