"""Database connection management service."""

import re
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.common.credentials import (
    CredentialNotFoundError,
    CredentialStorage,
    CredentialStorageError,
)
from src.common.dto import (
    ColumnInfo,
    ConnectionListResponse,
    ConnectionTestResponse,
    DatabaseConnectionConfig,
    TableDetails,
    TableInfo,
    TablePreviewResponse,
)
from src.common.logger import get_logger
from src.common.settings import Settings

logger = get_logger(__name__)

# Read-only SQL validation (reuse from SqlService pattern)
READ_ONLY_DENYLIST = re.compile(
    r"\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|MERGE|CREATE\s+TABLE|CREATE\s+INDEX)\b",
    re.IGNORECASE,
)

# SQL injection prevention for identifiers
VALID_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class ConnectionServiceError(Exception):
    """Base exception for connection service errors."""


class InvalidIdentifierError(ConnectionServiceError):
    """Raised when a table or schema name is invalid."""


def _validate_identifier(name: str, identifier_type: str = "identifier") -> None:
    """Validate that a name is a safe SQL identifier."""
    if not VALID_IDENTIFIER.match(name):
        raise InvalidIdentifierError(
            f"Invalid {identifier_type}: '{name}'. "
            "Only alphanumeric characters and underscores are allowed, "
            "and it must start with a letter or underscore."
        )


class ConnectionService:
    """Service for managing database connections and schema browsing."""

    def __init__(self, settings: Settings, credential_storage: CredentialStorage | None = None):
        self.settings = settings
        self._credential_storage = credential_storage
        self._engines: dict[str, AsyncEngine] = {}

    def _get_credential_storage(self) -> CredentialStorage:
        if self._credential_storage is None:
            if not self.settings.credential_encryption_key:
                raise ConnectionServiceError(
                    "CREDENTIAL_ENCRYPTION_KEY not configured. "
                    "Connection management requires an encryption key."
                )
            self._credential_storage = CredentialStorage(
                self.settings.credential_storage_path,
                self.settings.credential_encryption_key,
            )
        return self._credential_storage

    def _build_connection_url(self, config: DatabaseConnectionConfig) -> str:
        """Build PostgreSQL async connection URL."""
        ssl_params = ""
        if config.ssl_mode != "disable":
            ssl_params = f"?ssl={config.ssl_mode}"

        return (
            f"postgresql+asyncpg://{config.username}:{config.password}"
            f"@{config.host}:{config.port}/{config.database}{ssl_params}"
        )

    async def _get_engine(self, config: DatabaseConnectionConfig) -> AsyncEngine:
        """Get or create an engine for the given connection config."""
        cache_key = f"{config.host}:{config.port}/{config.database}/{config.username}"

        if cache_key not in self._engines:
            url = self._build_connection_url(config)
            self._engines[cache_key] = create_async_engine(
                url,
                pool_pre_ping=True,
                pool_size=2,
                max_overflow=3,
                pool_recycle=1800,
                echo=False,
                connect_args={"command_timeout": 30},
            )

        return self._engines[cache_key]

    async def test_connection(self, config: DatabaseConnectionConfig) -> ConnectionTestResponse:
        """Test a database connection and return status."""
        start_time = time.perf_counter()

        try:
            url = self._build_connection_url(config)
            engine = create_async_engine(
                url,
                pool_pre_ping=True,
                pool_size=1,
                echo=False,
                connect_args={"command_timeout": 10},
            )

            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT version()"))
                version = result.scalar()

            latency_ms = (time.perf_counter() - start_time) * 1000

            await engine.dispose()

            return ConnectionTestResponse(
                if_successful=True,
                message="Connection successful",
                server_version=version,
                latency_ms=round(latency_ms, 2),
            )

        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"Connection test failed: {e}")

            error_message = str(e)
            if "password authentication failed" in error_message.lower():
                message = "Authentication failed: Invalid username or password"
            elif "could not connect" in error_message.lower() or "connection refused" in error_message.lower():
                message = f"Could not connect to {config.host}:{config.port}"
            elif "does not exist" in error_message.lower():
                message = f"Database '{config.database}' does not exist"
            else:
                message = f"Connection failed: {error_message}"

            return ConnectionTestResponse(
                if_successful=False,
                message=message,
                server_version=None,
                latency_ms=round(latency_ms, 2),
            )

    def list_connections(self) -> ConnectionListResponse:
        """List all saved connections."""
        try:
            storage = self._get_credential_storage()
            connections = storage.list_connections()
            active_id = storage.get_active_connection_id()

            return ConnectionListResponse(
                connections=connections,
                active_connection_id=active_id,
            )
        except CredentialStorageError as e:
            logger.error(f"Failed to list connections: {e}")
            raise ConnectionServiceError(str(e))

    def get_connection(self, connection_id: str) -> DatabaseConnectionConfig:
        """Get a specific connection by ID."""
        try:
            storage = self._get_credential_storage()
            return storage.get_connection(connection_id)
        except CredentialNotFoundError:
            raise ConnectionServiceError(f"Connection '{connection_id}' not found")
        except CredentialStorageError as e:
            raise ConnectionServiceError(str(e))

    def save_connection(self, config: DatabaseConnectionConfig) -> DatabaseConnectionConfig:
        """Save a new connection."""
        try:
            storage = self._get_credential_storage()
            return storage.save_connection(config)
        except CredentialStorageError as e:
            raise ConnectionServiceError(str(e))

    def update_connection(
        self, connection_id: str, config: DatabaseConnectionConfig
    ) -> DatabaseConnectionConfig:
        """Update an existing connection."""
        try:
            storage = self._get_credential_storage()
            return storage.update_connection(connection_id, config)
        except CredentialNotFoundError:
            raise ConnectionServiceError(f"Connection '{connection_id}' not found")
        except CredentialStorageError as e:
            raise ConnectionServiceError(str(e))

    def delete_connection(self, connection_id: str) -> None:
        """Delete a connection."""
        try:
            storage = self._get_credential_storage()
            storage.delete_connection(connection_id)
        except CredentialNotFoundError:
            raise ConnectionServiceError(f"Connection '{connection_id}' not found")
        except CredentialStorageError as e:
            raise ConnectionServiceError(str(e))

    def set_active_connection(self, connection_id: str | None) -> None:
        """Set the active connection."""
        try:
            storage = self._get_credential_storage()
            storage.set_active_connection(connection_id)
        except CredentialNotFoundError:
            raise ConnectionServiceError(f"Connection '{connection_id}' not found")
        except CredentialStorageError as e:
            raise ConnectionServiceError(str(e))

    def _get_active_connection(self) -> DatabaseConnectionConfig:
        """Get the currently active connection config."""
        storage = self._get_credential_storage()
        config = storage.get_active_connection()
        if config is None:
            raise ConnectionServiceError("No active connection configured")
        return config

    async def get_tables(self, schema_name: str = "public") -> list[TableInfo]:
        """Get list of tables in the specified schema."""
        _validate_identifier(schema_name, "schema name")

        config = self._get_active_connection()
        engine = await self._get_engine(config)

        query = text("""
            SELECT
                table_schema,
                table_name,
                table_type,
                (
                    SELECT reltuples::bigint
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE c.relname = t.table_name
                    AND n.nspname = t.table_schema
                ) as row_count_estimate
            FROM information_schema.tables t
            WHERE table_schema = :schema_name
            AND table_type IN ('BASE TABLE', 'VIEW')
            ORDER BY table_name
        """)

        async with engine.connect() as conn:
            result = await conn.execute(query, {"schema_name": schema_name})
            rows = result.fetchall()

        tables = []
        for row in rows:
            tables.append(
                TableInfo(
                    schema_name=row[0],
                    table_name=row[1],
                    table_type=row[2],
                    row_count_estimate=int(row[3]) if row[3] and row[3] > 0 else None,
                )
            )

        return tables

    async def get_table_details(
        self, table_name: str, schema_name: str = "public"
    ) -> TableDetails:
        """Get detailed information about a table including columns."""
        _validate_identifier(table_name, "table name")
        _validate_identifier(schema_name, "schema name")

        config = self._get_active_connection()
        engine = await self._get_engine(config)

        # Get columns
        columns_query = text("""
            SELECT
                c.column_name,
                c.data_type,
                c.is_nullable = 'YES' as is_nullable,
                EXISTS (
                    SELECT 1 FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                        ON tc.constraint_name = kcu.constraint_name
                        AND tc.table_schema = kcu.table_schema
                    WHERE tc.constraint_type = 'PRIMARY KEY'
                    AND tc.table_schema = c.table_schema
                    AND tc.table_name = c.table_name
                    AND kcu.column_name = c.column_name
                ) as is_primary_key,
                EXISTS (
                    SELECT 1 FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                        ON tc.constraint_name = kcu.constraint_name
                        AND tc.table_schema = kcu.table_schema
                    WHERE tc.constraint_type = 'FOREIGN KEY'
                    AND tc.table_schema = c.table_schema
                    AND tc.table_name = c.table_name
                    AND kcu.column_name = c.column_name
                ) as is_foreign_key,
                (
                    SELECT ccu.table_name || '.' || ccu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                        ON tc.constraint_name = kcu.constraint_name
                        AND tc.table_schema = kcu.table_schema
                    JOIN information_schema.constraint_column_usage ccu
                        ON ccu.constraint_name = tc.constraint_name
                        AND ccu.table_schema = tc.table_schema
                    WHERE tc.constraint_type = 'FOREIGN KEY'
                    AND tc.table_schema = c.table_schema
                    AND tc.table_name = c.table_name
                    AND kcu.column_name = c.column_name
                    LIMIT 1
                ) as foreign_key_reference
            FROM information_schema.columns c
            WHERE c.table_schema = :schema_name
            AND c.table_name = :table_name
            ORDER BY c.ordinal_position
        """)

        # Get row count estimate
        count_query = text("""
            SELECT reltuples::bigint
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname = :table_name
            AND n.nspname = :schema_name
        """)

        async with engine.connect() as conn:
            columns_result = await conn.execute(
                columns_query, {"schema_name": schema_name, "table_name": table_name}
            )
            columns_rows = columns_result.fetchall()

            count_result = await conn.execute(
                count_query, {"schema_name": schema_name, "table_name": table_name}
            )
            count_row = count_result.fetchone()

        if not columns_rows:
            raise ConnectionServiceError(
                f"Table '{schema_name}.{table_name}' not found or has no columns"
            )

        columns = []
        for row in columns_rows:
            columns.append(
                ColumnInfo(
                    name=row[0],
                    data_type=row[1],
                    if_nullable=row[2],
                    if_primary_key=row[3],
                    if_foreign_key=row[4],
                    foreign_key_reference=row[5],
                )
            )

        row_count = int(count_row[0]) if count_row and count_row[0] and count_row[0] > 0 else None

        return TableDetails(
            schema_name=schema_name,
            table_name=table_name,
            columns=columns,
            row_count_estimate=row_count,
        )

    async def preview_table(
        self,
        table_name: str,
        schema_name: str = "public",
        limit: int = 50,
    ) -> TablePreviewResponse:
        """Preview table data with read-only enforcement."""
        _validate_identifier(table_name, "table name")
        _validate_identifier(schema_name, "schema name")

        if limit < 1 or limit > 1000:
            raise ConnectionServiceError("Limit must be between 1 and 1000")

        config = self._get_active_connection()
        engine = await self._get_engine(config)

        # Build safe query with validated identifiers
        query_str = f'SELECT * FROM "{schema_name}"."{table_name}" LIMIT :limit'

        # Extra safety: validate the generated query
        if READ_ONLY_DENYLIST.search(query_str):
            raise ConnectionServiceError("Invalid query detected")

        query = text(query_str)

        async with engine.connect() as conn:
            result = await conn.execute(query, {"limit": limit + 1})  # Fetch one extra to check has_more
            rows = result.fetchall()
            columns = list(result.keys())

        has_more = len(rows) > limit
        if has_more:
            rows = rows[:limit]

        # Convert rows to list of lists, handling special types
        rows_data: list[list[Any]] = []
        for row in rows:
            row_data: list[Any] = []
            for value in row:
                if value is None:
                    row_data.append(None)
                elif hasattr(value, "isoformat"):  # datetime, date, time
                    row_data.append(value.isoformat())
                elif isinstance(value, bytes):
                    row_data.append("<binary>")
                else:
                    row_data.append(value)
            rows_data.append(row_data)

        return TablePreviewResponse(
            schema_name=schema_name,
            table_name=table_name,
            columns=columns,
            rows=rows_data,
            total_rows=len(rows_data),
            has_more=has_more,
        )

    async def close(self) -> None:
        """Close all cached engines."""
        for engine in self._engines.values():
            await engine.dispose()
        self._engines.clear()


__all__ = ["ConnectionService", "ConnectionServiceError", "InvalidIdentifierError"]
