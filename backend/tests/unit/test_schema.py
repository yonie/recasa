"""init_db() must never change the schema of an existing index.

The live index on the Pi holds weeks of face detection and captioning, so
startup migrations are additive and idempotent only. schema_baseline.sql is
the exact sqlite_master of that index (SELECT sql || ';' ... ORDER BY sql).
"""

import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from backend.app import database
from backend.app.config import settings

BASELINE = Path(__file__).with_name("schema_baseline.sql")

# Indexes this code adds on top of the live schema (contract: CREATE INDEX IF
# NOT EXISTS only, each one measured). Nothing else may change.
ADDED_INDEXES = [
    "CREATE INDEX idx_photos_hash_flagged ON photos (file_hash, flagged_for_removal);",
]


def _schema(db_file: Path) -> list[str]:
    with sqlite3.connect(db_file) as conn:
        rows = conn.execute(
            "SELECT sql || ';' FROM sqlite_master WHERE sql IS NOT NULL ORDER BY sql"
        ).fetchall()
    return [r[0] for r in rows]


def _baseline(with_added: bool = True) -> list[str]:
    text = BASELINE.read_text()
    stmts = [stmt.strip() + ";" for stmt in text.split(";\n") if stmt.strip()]
    return sorted(stmts + (ADDED_INDEXES if with_added else []))


async def _init_on(db_source: Path | None, build_sql: str | None = None) -> Path:
    """Place an index at the app's DB path and run init_db() on it."""
    await database.engine.dispose()
    db_file = settings.data_dir / "db" / "recasa.db"
    for suffix in ("", "-wal", "-shm"):
        Path(f"{db_file}{suffix}").unlink(missing_ok=True)
    if db_source is not None:
        shutil.copyfile(db_source, db_file)
    if build_sql is not None:
        # The baseline is sorted by text, which puts indexes before tables.
        stmts = [s.strip() for s in build_sql.split(";\n") if s.strip()]
        stmts.sort(key=lambda s: not s.startswith("CREATE TABLE"))
        with sqlite3.connect(db_file) as conn:
            conn.executescript(";\n".join(stmts) + ";")
    await database.init_db()
    await database.engine.dispose()
    return db_file


@pytest.mark.asyncio
async def test_init_db_leaves_live_schema_untouched():
    """An index with the live schema comes out of init_db() byte-identical,
    plus only the listed indexes."""
    db_file = await _init_on(None, build_sql=BASELINE.read_text())
    assert _schema(db_file) == _baseline()
    assert set(_schema(db_file)) - set(_baseline(with_added=False)) == set(ADDED_INDEXES)


@pytest.mark.asyncio
async def test_init_db_is_idempotent():
    db_file = await _init_on(None, build_sql=BASELINE.read_text())
    await database.init_db()
    await database.engine.dispose()
    assert _schema(db_file) == _baseline()


@pytest.mark.asyncio
async def test_init_db_adds_late_columns_to_an_old_index():
    """An index from before the late columns gets them, with the live DDL."""
    old = BASELINE.read_text()
    for fragment in (
        (
            ", marked_for_print BOOLEAN DEFAULT 0 NOT NULL, exported_at DATETIME, "
            "flagged_for_removal BOOLEAN DEFAULT 0 NOT NULL, is_video BOOLEAN DEFAULT 0 NOT NULL, "
            "duration REAL"
        ),
        ", cover_file_hash TEXT, summary TEXT",
        ", ignored BOOLEAN DEFAULT 0",
    ):
        assert fragment in old
        old = old.replace(fragment, "")
    old = old.replace("CREATE INDEX idx_photo_tags_tag_id ON photo_tags (tag_id);\n", "")

    db_file = await _init_on(None, build_sql=old)
    assert _schema(db_file) == _baseline()


@pytest.mark.asyncio
async def test_init_db_creates_a_fresh_index():
    db_file = await _init_on(None)
    tables = {s.split()[2] for s in _schema(db_file) if s.startswith("CREATE TABLE")}
    baseline_tables = {s.split()[2] for s in _baseline() if s.startswith("CREATE TABLE")}
    assert tables == baseline_tables


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("RECASA_PRISTINE_DB"),
    reason="set RECASA_PRISTINE_DB to a copy of the real index to run",
)
async def test_init_db_on_real_index():
    """The real index (copied, never touched in place) keeps its exact schema."""
    db_file = await _init_on(Path(os.environ["RECASA_PRISTINE_DB"]))
    assert _schema(db_file) == _baseline()
