"""Unit-test setup: a throwaway data dir, photos dir and SQLite index.

Runs without Docker, network or ML models:

    python -m pytest backend/tests/unit      (from the repo root)

The app reads its settings and creates its database engine at import time, so
the environment is pointed at a temp dir here, before any app module loads.
"""

import os
import shutil
import tempfile
from pathlib import Path

_ROOT = Path(tempfile.mkdtemp(prefix="recasa-unit-"))
os.environ["DATA_DIR"] = str(_ROOT / "data")
os.environ["PHOTOS_DIR"] = str(_ROOT / "photos")
os.environ["WATCH_INTERVAL"] = "0"
(_ROOT / "data" / "db").mkdir(parents=True)
(_ROOT / "photos").mkdir()

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from backend.app import database  # noqa: E402
from backend.app.config import settings  # noqa: E402
from backend.app.models import Base  # noqa: E402
from backend.app.services import scanner  # noqa: E402


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_ROOT, ignore_errors=True)


@pytest.fixture
def data_dir() -> Path:
    return settings.data_dir


@pytest.fixture
def photos_dir() -> Path:
    return settings.photos_dir


@pytest.fixture
def stage_switches(monkeypatch):
    """Turn every optional stage on; tests flip them as needed."""
    monkeypatch.setattr(settings, "ENABLE_GEOCODING", True)
    monkeypatch.setattr(settings, "ENABLE_FACE_DETECTION", True)
    monkeypatch.setattr(settings, "ENABLE_CAPTIONING", True)
    return settings


@pytest_asyncio.fixture(loop_scope="function")
async def db(stage_switches):
    """A fresh, empty index plus empty photos and thumbnail dirs."""
    await database.engine.dispose()
    db_file = settings.data_dir / "db" / "recasa.db"
    for suffix in ("", "-wal", "-shm"):
        Path(f"{db_file}{suffix}").unlink(missing_ok=True)
    for d in (settings.photos_dir, settings.thumbnails_dir):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
    scanner._dir_snapshot.clear()
    scanner._seen_snapshot.clear()
    await database.init_db()
    yield database.async_session
    await database.engine.dispose()


__all__ = ["Base"]
