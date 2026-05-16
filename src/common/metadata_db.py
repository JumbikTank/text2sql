"""Text2SQL-owned metadata database (single Postgres+pgvector instance).

All per-connection table embeddings live here in a single shared `notes`
table partitioned by `connection_id`. This removes the requirement that
each user DB has pgvector + DDL privileges and avoids leaving artifacts
in customer schemas.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.common.logger import get_logger
from src.common.settings import Settings
from src.services.embedding_service import EMBEDDING_DIMENSIONS

logger = get_logger(__name__)


# Single shared embeddings table. The PK is (connection_id, schema_name,
# table_name) — every row is uniquely owned by one Text2SQL connection.
#
# We use ivfflat for cosine similarity. The list count is conservative
# (start tiny, scale up after data lands) — for our scale a single list
# scan is faster than the index until we have ~thousands of rows.
NOTES_DDL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS notes (
    connection_id UUID NOT NULL,
    schema_name   TEXT NOT NULL DEFAULT 'public',
    table_name    TEXT NOT NULL,
    description   TEXT,
    columns_info  TEXT,
    full_text     TEXT NOT NULL,
    embedding     vector({dim}) NOT NULL,
    metadata      JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (connection_id, schema_name, table_name)
);

CREATE INDEX IF NOT EXISTS idx_notes_connection
    ON notes (connection_id);

CREATE INDEX IF NOT EXISTS idx_notes_embedding
    ON notes USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 50);
""".format(dim=EMBEDDING_DIMENSIONS)


class MetadataDB:
    """Owns the singleton AsyncEngine pointed at the metadata Postgres."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._engine: AsyncEngine | None = None

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError(
                "MetadataDB.engine accessed before bootstrap(). "
                "Call await metadata_db.bootstrap() during app startup."
            )
        return self._engine

    def _build_url(self) -> str:
        s = self.settings
        return (
            f"postgresql+asyncpg://{s.metadata_db_user}:{s.metadata_db_password}"
            f"@{s.metadata_db_host}:{s.metadata_db_port}/{s.metadata_db_name}"
        )

    async def bootstrap(self) -> None:
        """Create engine, ensure pgvector + notes table exist."""
        url = self._build_url()
        logger.info(
            f"Connecting to metadata DB at "
            f"{self.settings.metadata_db_host}:{self.settings.metadata_db_port}"
            f"/{self.settings.metadata_db_name}"
        )
        self._engine = create_async_engine(
            url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            pool_recycle=1800,
            echo=False,
        )

        async with self._engine.begin() as conn:
            for stmt in [s.strip() for s in NOTES_DDL.split(";") if s.strip()]:
                await conn.execute(text(stmt))
        logger.info("Metadata DB schema ready")

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None


__all__ = ["MetadataDB"]
