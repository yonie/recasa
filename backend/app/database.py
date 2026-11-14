import logging
from collections.abc import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.app.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_size=5,
    max_overflow=10,
)


# Per-connection SQLite settings.
#   journal_mode=WAL      concurrent readers with a single writer, drastically
#                         fewer 'database is locked' errors than the default
#   synchronous=NORMAL    safe with WAL; fsync at checkpoints, not every commit
#   mmap_size             read the index through the OS page cache instead of
#                         a read() per page. Covers the whole 0.4 GB index
#                         with room to grow; it is address space, not RAM.
#                         Halves the big aggregate queries (tag counts).
#   cache_size            16 MB page cache per connection (default 2 MB)
#   temp_store=MEMORY     sorts and DISTINCTs without an index use RAM, not
#                         temp files on the SD card or SSD
# Deliberately no ANALYZE / PRAGMA optimize: they add sqlite_stat tables to
# the schema and can change query plans, and with them the row order of
# queries whose ORDER BY leaves ties.
_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA busy_timeout=30000",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA mmap_size=536870912",
    "PRAGMA cache_size=-16384",
    "PRAGMA temp_store=MEMORY",
)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    """Apply _PRAGMAS to every new connection."""
    cursor = dbapi_connection.cursor()
    for pragma in _PRAGMAS:
        cursor.execute(pragma)
    cursor.close()


async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def init_db() -> None:
    """Create missing tables and bring an existing index up to the current schema."""
    from backend.app.models import Base

    # Ensure the database directory exists
    db_dir = settings.data_dir / "db"
    db_dir.mkdir(parents=True, exist_ok=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate(conn)

    logger.info("Database initialized at %s", settings.database_url)


# Columns added after their table already existed in deployed indexes.
# create_all() only creates missing tables, never missing columns, so these
# are added here, idempotently, on every startup. Schema changes are only ever
# additive: the index holds weeks of face detection and captioning and is
# never dropped and rebuilt. The DDL matches what the live index carries.
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "photos": {
        "marked_for_print": "BOOLEAN DEFAULT 0 NOT NULL",
        "exported_at": "DATETIME",
        "flagged_for_removal": "BOOLEAN DEFAULT 0 NOT NULL",
        "is_video": "BOOLEAN DEFAULT 0 NOT NULL",
        "duration": "REAL",
    },
    "events": {
        "cover_file_hash": "TEXT",
        "summary": "TEXT",
    },
    "persons": {
        "ignored": "BOOLEAN DEFAULT 0",
    },
}

# Indexes added after tables already existed (create_all won't add these).
_ADDED_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_photo_tags_tag_id ON photo_tags (tag_id)",
    # Faces that carry an encoding, for the distinct-faces count on the
    # pipeline page (polled every 3s). Partial, so it skips the no-face marker
    # rows. processing-stats 132ms -> 59ms on the Pi.
    (
        "CREATE INDEX IF NOT EXISTS ix_faces_encoded_file_hash"
        " ON faces (file_hash) WHERE encoding IS NOT NULL"
    ),
)


async def _migrate(conn: AsyncConnection) -> None:
    """Add the columns and indexes that create_all won't add to existing DBs."""
    for table, columns in _ADDED_COLUMNS.items():
        result = await conn.execute(text(f"PRAGMA table_info({table})"))
        existing = {row[1] for row in result}
        for name, ddl in columns.items():
            if name not in existing:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                logger.info("Added column %s.%s", table, name)

    for ddl in _ADDED_INDEXES:
        await conn.execute(text(ddl))
