"""Small builders shared by the unit tests."""

import os
import random
from datetime import datetime
from pathlib import Path

from PIL import Image

from backend.app.config import settings
from backend.app.models import Photo, PhotoPath


def write_jpeg(path: Path, seed: int = 0, size: tuple[int, int] = (64, 48)) -> Path:
    """A real, decodable JPEG over the scanner's 1 KB minimum (noise compresses badly)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(seed)
    img = Image.new("RGB", size)
    img.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
                 for _ in range(size[0] * size[1])])
    img.save(path, "JPEG", quality=95)
    assert path.stat().st_size >= 1024
    return path


def set_mtime(path: Path, ts: float) -> None:
    os.utime(path, (ts, ts))


def touch_thumb(file_hash: str) -> Path:
    """Create the file that marks the thumbnail stage done."""
    p = settings.thumbnails_dir / file_hash[:2] / f"{file_hash}_200.webp"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"webp")
    return p


def photo_row(file_hash: str, path: str = "", **kw) -> list:
    """A Photo plus its PhotoPath, defaulting to a fully EXIF'd plain photo."""
    path = path or f"{file_hash}.jpg"
    values = {
        "file_hash": file_hash,
        "file_path": path,
        "file_name": Path(path).name,
        "file_size": 2048,
        "file_modified": datetime(2024, 1, 1, 12, 0, 0),
        "date_taken": datetime(2024, 1, 1, 12, 0, 0),
        "date_source": "exif",
    }
    values.update(kw)
    return [Photo(**values), PhotoPath(file_hash=file_hash, file_path=path)]


def h(n: int) -> str:
    """A fake 64-char file hash."""
    return f"{n:064x}"
