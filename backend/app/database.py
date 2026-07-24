import logging
from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_size=5,
    max_overflow=10,
)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    """Configure SQLite for better concurrency on every new connection.

    WAL mode allows concurrent readers with a single writer, drastically
    reducing 'database is locked' errors compared to the default journal mode.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def init_db() -> None:
    """Create all database tables."""
    from backend.app.models import Base  # noqa: F811

    # Ensure the database directory exists
    db_dir = settings.data_dir / "db"
    db_dir.mkdir(parents=True, exist_ok=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_photo_columns(conn)

    logger.info("Database initialized at %s", settings.database_url)


async def _migrate_photo_columns(conn) -> None:
    """Add columns to the photos table that create_all won't add to existing DBs."""
    from sqlalchemy import text

    result = await conn.execute(text("PRAGMA table_info(photos)"))
    existing = {row[1] for row in result}

    new_columns = {
        "marked_for_print": "BOOLEAN DEFAULT 0 NOT NULL",
        "exported_at": "DATETIME",
    }
    for name, ddl in new_columns.items():
        if name not in existing:
            await conn.execute(text(f"ALTER TABLE photos ADD COLUMN {name} {ddl}"))
            logger.info("Added column photos.%s", name)

    # Indexes added after tables already existed (create_all won't add these).
    await conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_photo_tags_tag_id ON photo_tags (tag_id)")
    )
