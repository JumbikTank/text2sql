"""Embedding generation and table metadata storage service.

All writes/reads go through the Text2SQL-owned metadata DB (a single shared
`notes` table partitioned by `connection_id`). The user database is no
longer required to host pgvector or have DDL privileges.
"""

import json
from typing import Any

from sentence_transformers import SentenceTransformer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from src.common.logger import get_logger

logger = get_logger(__name__)

# Embedding model configuration
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS = 384


class EmbeddingServiceError(Exception):
    """Base exception for embedding service errors."""


class EmbeddingService:
    """Service for generating embeddings and managing the shared notes table.

    The metadata engine is provided once at construction and used for all
    writes/reads. Per-connection identity is carried in the `connection_id`
    column of the shared `notes` table.
    """

    def __init__(self, metadata_engine: AsyncEngine | None = None) -> None:
        self._model: SentenceTransformer | None = None
        self._metadata_engine = metadata_engine

    def set_metadata_engine(self, engine: AsyncEngine) -> None:
        """Late binding so the lifespan can construct EmbeddingService
        before MetadataDB.bootstrap() finishes."""
        self._metadata_engine = engine

    def _engine(self) -> AsyncEngine:
        if self._metadata_engine is None:
            raise EmbeddingServiceError(
                "Metadata engine not configured. "
                "Call set_metadata_engine() during app startup."
            )
        return self._metadata_engine

    def _get_model(self) -> SentenceTransformer:
        """Lazily load the sentence transformer model."""
        if self._model is None:
            logger.info(f"Loading embedding model: {EMBEDDING_MODEL}")
            self._model = SentenceTransformer(EMBEDDING_MODEL)
            logger.info("Embedding model loaded successfully")
        return self._model

    def generate_embedding(self, text_content: str) -> list[float]:
        """Generate embedding vector for the given text."""
        model = self._get_model()
        embedding = model.encode(text_content, convert_to_numpy=True)
        return embedding.tolist()

    async def upsert_table_embedding(
        self,
        connection_id: str,
        table_name: str,
        schema_name: str,
        description: str | None,
        columns_info: str,
        foreign_keys: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Insert or update a single table's embedding row in `notes`."""
        full_text = self._build_full_text(
            table_name, description, columns_info, foreign_keys
        )

        embedding = self.generate_embedding(full_text)
        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

        metadata_json = json.dumps(metadata) if metadata else "{}"

        async with self._engine().begin() as conn:
            await conn.execute(
                text("""
                INSERT INTO notes
                    (connection_id, schema_name, table_name,
                     description, columns_info, full_text, embedding,
                     metadata, updated_at)
                VALUES
                    (CAST(:connection_id AS UUID), :schema_name, :table_name,
                     :description, :columns_info, :full_text,
                     CAST(:embedding AS vector),
                     CAST(:metadata AS JSONB), now())
                ON CONFLICT (connection_id, schema_name, table_name)
                DO UPDATE SET
                    description  = EXCLUDED.description,
                    columns_info = EXCLUDED.columns_info,
                    full_text    = EXCLUDED.full_text,
                    embedding    = EXCLUDED.embedding,
                    metadata     = EXCLUDED.metadata,
                    updated_at   = now()
            """),
                {
                    "connection_id": connection_id,
                    "schema_name": schema_name,
                    "table_name": table_name,
                    "description": description,
                    "columns_info": columns_info,
                    "full_text": full_text,
                    "embedding": embedding_str,
                    "metadata": metadata_json,
                },
            )

        logger.debug(f"Upserted embedding for {schema_name}.{table_name}")

    async def remove_table_embedding(
        self,
        connection_id: str,
        table_name: str,
        schema_name: str = "public",
    ) -> None:
        async with self._engine().begin() as conn:
            await conn.execute(
                text("""
                DELETE FROM notes
                WHERE connection_id = CAST(:connection_id AS UUID)
                  AND schema_name = :schema_name
                  AND table_name = :table_name
                """),
                {
                    "connection_id": connection_id,
                    "schema_name": schema_name,
                    "table_name": table_name,
                },
            )
        logger.debug(f"Removed embedding for {schema_name}.{table_name}")

    async def remove_connection(self, connection_id: str) -> None:
        """Drop every embedding for a given connection (e.g. when the
        connection is deleted)."""
        async with self._engine().begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM notes WHERE connection_id = CAST(:cid AS UUID)"
                ),
                {"cid": connection_id},
            )
        logger.info(f"Removed all embeddings for connection {connection_id}")

    async def get_known_tables(
        self,
        connection_id: str,
        schema_name: str = "public",
    ) -> set[str]:
        """Return the set of table names tracked for a connection."""
        async with self._engine().connect() as conn:
            result = await conn.execute(
                text("""
                SELECT table_name FROM notes
                WHERE connection_id = CAST(:cid AS UUID)
                  AND schema_name = :schema_name
                """),
                {"cid": connection_id, "schema_name": schema_name},
            )
            return {row[0] for row in result.fetchall()}

    async def count_embeddings(self, connection_id: str) -> int:
        """Return how many embedding rows exist for a connection. Used by
        MessageService to decide whether an initial scan is needed."""
        async with self._engine().connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM notes "
                    "WHERE connection_id = CAST(:cid AS UUID)"
                ),
                {"cid": connection_id},
            )
            return int(result.scalar() or 0)

    @staticmethod
    def _build_full_text(
        table_name: str,
        description: str | None,
        columns_info: str,
        foreign_keys: str | None = None,
    ) -> str:
        parts = [f"Table: {table_name}"]

        if description:
            parts.append(f"Description: {description}")

        if columns_info:
            parts.append(f"Columns (use exact names): {columns_info}")

        if foreign_keys:
            fk_count = foreign_keys.count("->")
            if fk_count >= 2:
                parts.append("Type: Junction/linking table (connects other tables)")
            parts.append(f"Foreign Keys: {foreign_keys}")
            parts.append(
                "Note: To get related data (like names), JOIN with the referenced tables"
            )

        return "\n".join(parts)


__all__ = ["EmbeddingService", "EmbeddingServiceError", "EMBEDDING_DIMENSIONS"]
