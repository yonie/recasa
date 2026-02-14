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

    # Ollama
    ollama_url: str = "http://ollama:11434"
    ollama_model: str = "qwen3-vl:30b-a3b-instruct"

    # Processing stages (enable/disable per stage)
    # EXIF, Thumbnails, and Hashing are always enabled (core functionality)
    ENABLE_GEOCODING: bool = True
    ENABLE_FACE_DETECTION: bool = False
    ENABLE_CAPTIONING: bool = False

    # Maximum number of photos to process concurrently (limits memory usage)
    # Each concurrent photo uses memory for image loading, thumbnails, face detection, etc.
    # Recommended: 2-3 for systems with limited RAM, higher for systems with more RAM
    max_concurrent: int = 2

    # Supported file extensions
    photo_extensions: set[str] = {
        ".jpg", ".jpeg", ".png", ".webp",
        ".heic", ".heif",
        ".tiff", ".tif", ".bmp",
    }
    video_extensions: set[str] = {
        ".mp4", ".mov", ".avi", ".mkv",
    }

    # Log level
    log_level: str = "info"

    model_config = {"env_prefix": "", "case_sensitive": False}


settings = Settings()
