"""Background table scanning service."""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Awaitable


def _utcnow() -> datetime:
    return datetime.now(UTC)

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.common.credentials import CredentialStorage
from src.common.dto import DatabaseConnectionConfig
from src.common.logger import get_logger
from src.common.settings import Settings
from src.services.embedding_service import EmbeddingService

logger = get_logger(__name__)


@dataclass
class ScanResult:
    """Result of a table scan operation."""

    connection_id: str
    tables_added: list[str] = field(default_factory=list)
    tables_removed: list[str] = field(default_factory=list)
    total_tables: int = 0
    scan_time: datetime = field(default_factory=_utcnow)
    if_success: bool = True
    error_message: str | None = None


class ScannerServiceError(Exception):
    """Base exception for scanner service errors."""


# Type alias for notification callback
NotificationCallback = Callable[[str, str, list[str], str], Awaitable[None]]


class ScannerService:
    """Service for background table scanning and embedding generation."""

    def __init__(
        self,
        settings: Settings,
        embedding_service: EmbeddingService,
        notification_callback: NotificationCallback | None = None,
    ) -> None:
        self.settings = settings
        self.embedding_service = embedding_service
        self.notification_callback = notification_callback
        self._engines: dict[str, AsyncEngine] = {}

    def _get_credential_storage(self) -> CredentialStorage:
        """Get the credential storage instance."""
        if not self.settings.credential_encryption_key:
            raise ScannerServiceError(
                "CREDENTIAL_ENCRYPTION_KEY not configured. "
                "Scanner requires an encryption key."
            )
        return CredentialStorage(
            self.settings.credential_storage_path,
            self.settings.credential_encryption_key,
        )

    def _build_connection_url(self, config: DatabaseConnectionConfig) -> str:
        """Build PostgreSQL async connection URL."""
        ssl_params = ""
        if config.ssl_mode != "disable":
            ssl_params = f"?ssl={config.ssl_mode}"

        return (
            f"postgresql+asyncpg://{config.username}:{config.password}"
            f"@{config.host}:{config.port}/{config.database}{ssl_params}"
        )

    async def _get_engine(self, connection_id: str) -> AsyncEngine:
        """Get or create an engine for the given connection."""
        if connection_id not in self._engines:
            storage = self._get_credential_storage()
            # Need the real password, not the masked one the public API returns.
            config = storage.get_connection_with_password(connection_id)

            url = self._build_connection_url(config)
            self._engines[connection_id] = create_async_engine(
                url,
                pool_pre_ping=True,
                pool_size=2,
                max_overflow=3,
                pool_recycle=1800,
                echo=False,
                connect_args={"command_timeout": 30},
            )

        return self._engines[connection_id]

    async def _notify(
        self,
        notification_type: str,
        connection_id: str,
        tables: list[str],
        message: str,
    ) -> None:
        """Send notification if callback is set."""
        if self.notification_callback:
            try:
                await self.notification_callback(
                    notification_type, connection_id, tables, message
                )
            except Exception as e:
                logger.error(f"Notification callback failed: {e}")

    async def get_database_tables(
        self,
        engine: AsyncEngine,
        schema_name: str = "public",
    ) -> list[dict[str, Any]]:
        """Get all tables from the database with their metadata.

        Args:
            engine: SQLAlchemy async engine
            schema_name: Schema to scan

        Returns:
            List of table info dictionaries
        """
        query = text("""
            SELECT
                t.table_name,
                t.table_type,
                pg_catalog.obj_description(c.oid, 'pg_class') as table_comment,
                (
                    SELECT string_agg(
                        col.column_name || ' (' || col.data_type || ')',
                        ', '
                        ORDER BY col.ordinal_position
                    )
                    FROM information_schema.columns col
                    WHERE col.table_schema = t.table_schema
                    AND col.table_name = t.table_name
                ) as columns_list,
                (
                    SELECT string_agg(
                        kcu.column_name || ' -> ' || ccu.table_name || '.' || ccu.column_name,
                        '; '
                    )
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                        ON tc.constraint_name = kcu.constraint_name
                        AND tc.table_schema = kcu.table_schema
                    JOIN information_schema.constraint_column_usage ccu
                        ON ccu.constraint_name = tc.constraint_name
                        AND ccu.table_schema = tc.table_schema
                    WHERE tc.constraint_type = 'FOREIGN KEY'
                    AND tc.table_name = t.table_name
                    AND tc.table_schema = t.table_schema
                ) as foreign_keys
            FROM information_schema.tables t
            LEFT JOIN pg_catalog.pg_class c ON c.relname = t.table_name
            LEFT JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace AND n.nspname = t.table_schema
            WHERE t.table_schema = :schema_name
            AND t.table_type IN ('BASE TABLE', 'VIEW')
            ORDER BY t.table_name
        """)

        async with engine.connect() as conn:
            result = await conn.execute(query, {"schema_name": schema_name})
            rows = result.fetchall()

        tables = []
        for row in rows:
            tables.append({
                "table_name": row[0],
                "table_type": row[1],
                "table_comment": row[2],
                "columns_list": row[3] or "",
                "foreign_keys": row[4] or "",
            })

        # Enrich columns_list with per-column allowed values from three
        # sources, in priority order:
        #   1. Native Postgres ENUM types (pg_enum)         — always.
        #   2. CHECK (col IN (…)) constraints (pg_constraint)— always.
        #   3. SELECT DISTINCT sampling                      — gated on row count.
        # The first two are catalog-derived (cheap, authoritative). The third
        # is a fallback for "enums by convention" in plain varchar columns.
        for table_info in tables:
            try:
                hints = await self._collect_value_hints(
                    engine, schema_name, table_info["table_name"]
                )
                if hints:
                    extras = "; ".join(
                        f"{col} values: {', '.join(repr(v) for v in vals)}"
                        for col, vals in hints.items()
                    )
                    table_info["columns_list"] = (
                        f"{table_info['columns_list']} | {extras}"
                        if table_info["columns_list"]
                        else extras
                    )
            except Exception as e:
                logger.debug(
                    f"Value hint collection skipped for "
                    f"{table_info['table_name']}: {e}"
                )

        return tables

    # Minimum estimated row count before we bother sampling DISTINCT values.
    # Catalog-derived hints (pg_enum, CHECK) are unaffected by this gate.
    _SAMPLE_MIN_ROWS = 5

    # CHECK definitions normalize 'value' literals; this matches a single
    # 'string' literal, allowing '' as an escaped single quote inside.
    _CHECK_LITERAL_RE = re.compile(r"'((?:[^']|'')*)'")

    async def _collect_value_hints(
        self,
        engine: AsyncEngine,
        schema_name: str,
        table_name: str,
    ) -> dict[str, list[str]]:
        """Combine catalog hints (pg_enum, CHECK) with sampled values."""
        async with engine.connect() as conn:
            enum_hints = await self._get_enum_column_values(
                conn, schema_name, table_name
            )
            check_hints = await self._get_check_constraint_values(
                conn, schema_name, table_name
            )
            row_estimate = await self._get_row_count_estimate(
                conn, schema_name, table_name
            )

            hints: dict[str, list[str]] = {}
            hints.update(enum_hints)
            # CHECK supplements but never overrides ENUM (ENUM is more authoritative).
            for col, values in check_hints.items():
                hints.setdefault(col, values)

            if row_estimate >= self._SAMPLE_MIN_ROWS:
                sampled = await self._sample_low_cardinality_values(
                    conn,
                    schema_name,
                    table_name,
                    skip_columns=set(hints.keys()),
                )
                for col, values in sampled.items():
                    hints.setdefault(col, values)
            elif row_estimate > 0:
                logger.debug(
                    f"Skipping DISTINCT sampling for "
                    f"{schema_name}.{table_name} "
                    f"(estimated rows {row_estimate} < {self._SAMPLE_MIN_ROWS})"
                )

        return hints

    @staticmethod
    async def _get_enum_column_values(
        conn,
        schema_name: str,
        table_name: str,
    ) -> dict[str, list[str]]:
        """Return all labels for columns typed with a Postgres ENUM type.

        Always include these — cardinality doesn't matter, the catalog is
        the source of truth.
        """
        query = text("""
            SELECT a.attname AS column_name,
                   array_agg(e.enumlabel ORDER BY e.enumsortorder) AS labels
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_type t ON t.oid = a.atttypid
            JOIN pg_enum e ON e.enumtypid = t.oid
            WHERE n.nspname = :schema
              AND c.relname = :tbl
              AND t.typtype = 'e'
              AND a.attnum > 0
              AND NOT a.attisdropped
            GROUP BY a.attname
        """)
        result = await conn.execute(
            query, {"schema": schema_name, "tbl": table_name}
        )
        return {row[0]: list(row[1]) for row in result.fetchall()}

    @classmethod
    async def _get_check_constraint_values(
        cls,
        conn,
        schema_name: str,
        table_name: str,
    ) -> dict[str, list[str]]:
        """Extract enum values from single-column CHECK (col IN (...)) and
        CHECK (col = ANY (ARRAY[...])) constraints. Multi-column CHECKs
        (e.g. range guards) are skipped — conkey length filter does that.
        """
        query = text("""
            SELECT a.attname AS column_name,
                   pg_get_constraintdef(con.oid, true) AS def
            FROM pg_constraint con
            JOIN pg_class c ON c.oid = con.conrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a ON a.attrelid = con.conrelid
                               AND a.attnum = con.conkey[1]
            WHERE n.nspname = :schema
              AND c.relname = :tbl
              AND con.contype = 'c'
              AND array_length(con.conkey, 1) = 1
        """)
        result = await conn.execute(
            query, {"schema": schema_name, "tbl": table_name}
        )

        out: dict[str, list[str]] = {}
        for col_name, definition in result.fetchall():
            # Only IN-list / = ANY (ARRAY ...) shapes encode enums; range
            # checks ('CHECK (price > 0)') have no string literals and we
            # skip them naturally below.
            if not re.search(r"\b(IN|ANY)\b", definition, re.IGNORECASE):
                continue
            literals = [
                m.group(1).replace("''", "'")
                for m in cls._CHECK_LITERAL_RE.finditer(definition)
            ]
            # De-dupe but preserve order of first occurrence.
            seen: set[str] = set()
            unique: list[str] = []
            for v in literals:
                if v not in seen:
                    seen.add(v)
                    unique.append(v)
            if unique:
                # If the same column has multiple CHECK constraints, take
                # the intersection — the column must satisfy all of them.
                if col_name in out:
                    intersection = [v for v in out[col_name] if v in seen]
                    out[col_name] = intersection or unique
                else:
                    out[col_name] = unique
        return out

    @staticmethod
    async def _get_row_count_estimate(
        conn,
        schema_name: str,
        table_name: str,
    ) -> int:
        """Cheap row-count estimate from pg_class.reltuples.

        Returns 0 when no estimate is available (fresh table, never
        analyzed). The estimate is good enough for the sampling gate; for a
        precise count callers can fall back to COUNT(*) themselves.
        """
        query = text("""
            SELECT c.reltuples::bigint AS rows_estimate
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = :schema AND c.relname = :tbl
        """)
        result = await conn.execute(
            query, {"schema": schema_name, "tbl": table_name}
        )
        row = result.first()
        if row is None or row[0] is None:
            return 0
        # Postgres 14+ uses -1 as "no estimate yet"; treat as 0.
        return max(int(row[0]), 0)

    async def _sample_low_cardinality_values(
        self,
        conn,
        schema_name: str,
        table_name: str,
        max_distinct: int = 12,
        skip_columns: set[str] | None = None,
    ) -> dict[str, list[str]]:
        """Return distinct values for short text/varchar columns whose
        cardinality is at or below `max_distinct`. Skips columns already
        covered by catalog hints. Errors per-column are swallowed.
        """
        skip_columns = skip_columns or set()

        cols_query = text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = :schema_name
              AND table_name = :table_name
              AND data_type IN (
                'character varying', 'varchar',
                'text', 'char', 'character'
              )
            ORDER BY ordinal_position
        """)

        # Per-value length cap so we don't embed long paragraphs even when
        # cardinality is low.
        max_value_len = 120

        cols_result = await conn.execute(
            cols_query,
            {"schema_name": schema_name, "table_name": table_name},
        )
        candidate_cols = [
            r[0] for r in cols_result.fetchall() if r[0] not in skip_columns
        ]

        samples: dict[str, list[str]] = {}
        for col_name in candidate_cols:
            try:
                distinct_query = text(
                    f'SELECT DISTINCT "{col_name}" '
                    f'FROM "{schema_name}"."{table_name}" '
                    f'WHERE "{col_name}" IS NOT NULL '
                    f'LIMIT :lim'
                )
                result = await conn.execute(
                    distinct_query, {"lim": max_distinct + 1}
                )
                values = [r[0] for r in result.fetchall()]
                if 0 < len(values) <= max_distinct:
                    truncated = [
                        (str(v)[:max_value_len] + "…")
                        if len(str(v)) > max_value_len
                        else str(v)
                        for v in values
                    ]
                    samples[col_name] = truncated
            except Exception:
                continue

        return samples

    async def scan_connection(
        self,
        connection_id: str,
        schema_name: str = "public",
        table_allowlist: set[str] | None = None,
    ) -> ScanResult:
        """Scan a connection for table changes.

        The user-DB engine is used only for catalog reads + value sampling.
        All embedding writes go to the metadata DB via EmbeddingService.

        Args:
            connection_id: The connection to scan
            schema_name: Schema to scan
            table_allowlist: When set, only tables whose lower-cased name
                is in this set are scanned. Used by the BIRD bench to
                give each logical BIRD db_id its own subset of the
                combined `bird_dev` Postgres database.

        Returns:
            ScanResult with added/removed tables
        """
        logger.info(f"Starting scan for connection: {connection_id}")

        try:
            engine = await self._get_engine(connection_id)

            # Get current tables from the user database
            db_tables = await self.get_database_tables(engine, schema_name)
            if table_allowlist is not None:
                allow_lower = {t.lower() for t in table_allowlist}
                db_tables = [
                    t for t in db_tables if t["table_name"].lower() in allow_lower
                ]
            current_table_names = {t["table_name"] for t in db_tables}

            # Get known tables from the metadata DB
            known_tables = await self.embedding_service.get_known_tables(
                connection_id, schema_name
            )

            tables_added = list(current_table_names - known_tables)
            tables_removed = list(known_tables - current_table_names)

            # Refresh embeddings for every current table — ScannerService
            # also picks up column / FK / value-hint changes on existing
            # tables, so we don't want to skip rows that already exist.
            for table_info in db_tables:
                await self.embedding_service.upsert_table_embedding(
                    connection_id=connection_id,
                    table_name=table_info["table_name"],
                    schema_name=schema_name,
                    description=table_info["table_comment"],
                    columns_info=table_info["columns_list"],
                    foreign_keys=table_info["foreign_keys"],
                    metadata={
                        "table_type": table_info["table_type"],
                        "scanned_at": _utcnow().isoformat(),
                    },
                )
            if tables_added:
                logger.info(
                    f"Added {len(tables_added)} embedding(s): {tables_added}"
                )

            for table_name in tables_removed:
                await self.embedding_service.remove_table_embedding(
                    connection_id=connection_id,
                    table_name=table_name,
                    schema_name=schema_name,
                )
                logger.info(f"Removed embedding for table: {table_name}")

            result = ScanResult(
                connection_id=connection_id,
                tables_added=tables_added,
                tables_removed=tables_removed,
                total_tables=len(current_table_names),
                if_success=True,
            )

            # Send notifications
            if tables_added:
                await self._notify(
                    "tables_added",
                    connection_id,
                    tables_added,
                    f"Found {len(tables_added)} new table(s)",
                )

            if tables_removed:
                await self._notify(
                    "tables_removed",
                    connection_id,
                    tables_removed,
                    f"Removed {len(tables_removed)} table(s)",
                )

            if not tables_added and not tables_removed:
                await self._notify(
                    "scan_complete",
                    connection_id,
                    [],
                    f"Scan complete. {len(current_table_names)} tables, no changes.",
                )

            logger.info(
                f"Scan complete for {connection_id}: "
                f"+{len(tables_added)} -{len(tables_removed)} tables"
            )

            return result

        except Exception as e:
            error_msg = f"Scan failed for {connection_id}: {e}"
            logger.error(error_msg)

            await self._notify(
                "scan_error",
                connection_id,
                [],
                str(e),
            )

            return ScanResult(
                connection_id=connection_id,
                if_success=False,
                error_message=str(e),
            )

    async def refresh_table_embedding(
        self,
        connection_id: str,
        table_name: str,
        schema_name: str = "public",
    ) -> None:
        """Refresh embedding for a specific table."""
        logger.info(f"Refreshing embedding for {schema_name}.{table_name}")

        engine = await self._get_engine(connection_id)

        query = text("""
            SELECT
                pg_catalog.obj_description(c.oid, 'pg_class') as table_comment,
                (
                    SELECT string_agg(
                        col.column_name || ' (' || col.data_type || ')',
                        ', '
                        ORDER BY col.ordinal_position
                    )
                    FROM information_schema.columns col
                    WHERE col.table_schema = :schema_name
                    AND col.table_name = :table_name
                ) as columns_list
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname = :table_name
            AND n.nspname = :schema_name
        """)

        async with engine.connect() as conn:
            result = await conn.execute(
                query, {"schema_name": schema_name, "table_name": table_name}
            )
            row = result.fetchone()

        if not row:
            raise ScannerServiceError(f"Table {schema_name}.{table_name} not found")

        await self.embedding_service.upsert_table_embedding(
            connection_id=connection_id,
            table_name=table_name,
            schema_name=schema_name,
            description=row[0],
            columns_info=row[1] or "",
            metadata={"refreshed_at": _utcnow().isoformat()},
        )

    async def close(self) -> None:
        """Close all cached engines."""
        for engine in self._engines.values():
            await engine.dispose()
        self._engines.clear()


__all__ = ["ScannerService", "ScannerServiceError", "ScanResult", "NotificationCallback"]
