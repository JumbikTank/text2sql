from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


# Database Connection DTOs
class DatabaseConnectionConfig(BaseModel):
    """Configuration for a database connection."""

    id: str | None = Field(default=None, description="Unique connection identifier")
    name: str = Field(default="default", description="Connection display name")
    host: str = Field(..., description="Database host")
    port: int = Field(default=5432, description="Database port")
    database: str = Field(..., description="Database name")
    username: str = Field(..., description="Database username")
    password: str = Field(..., repr=False, description="Database password")
    ssl_mode: Literal["disable", "require", "verify-ca", "verify-full"] = Field(
        default="disable", description="SSL mode for connection"
    )


class ConnectionTestResponse(BaseModel):
    """Response from testing a database connection."""

    if_successful: bool = Field(..., description="Whether connection test succeeded")
    message: str = Field(..., description="Status message")
    server_version: str | None = Field(
        default=None, description="Database server version"
    )
    latency_ms: float | None = Field(
        default=None, description="Connection latency in milliseconds"
    )


class TableInfo(BaseModel):
    """Basic information about a database table."""

    schema_name: str = Field(..., description="Schema name")
    table_name: str = Field(..., description="Table name")
    table_type: Literal["BASE TABLE", "VIEW"] = Field(
        ..., description="Type of table object"
    )
    row_count_estimate: int | None = Field(
        default=None, description="Estimated row count"
    )


class ColumnInfo(BaseModel):
    """Information about a table column."""

    name: str = Field(..., description="Column name")
    data_type: str = Field(..., description="Column data type")
    if_nullable: bool = Field(..., description="Whether column allows NULL values")
    if_primary_key: bool = Field(default=False, description="Whether column is a primary key")
    if_foreign_key: bool = Field(default=False, description="Whether column is a foreign key")
    foreign_key_reference: str | None = Field(
        default=None, description="Foreign key reference (table.column)"
    )


class TableDetails(BaseModel):
    """Detailed information about a table including columns."""

    schema_name: str = Field(..., description="Schema name")
    table_name: str = Field(..., description="Table name")
    columns: list[ColumnInfo] = Field(..., description="List of columns")
    row_count_estimate: int | None = Field(
        default=None, description="Estimated row count"
    )


class TablePreviewRequest(BaseModel):
    """Request for previewing table data."""

    schema_name: str = Field(default="public", description="Schema name")
    table_name: str = Field(..., description="Table name")
    limit: int = Field(default=50, ge=1, le=1000, description="Number of rows to preview")


class TablePreviewResponse(BaseModel):
    """Response containing table preview data."""

    schema_name: str = Field(..., description="Schema name")
    table_name: str = Field(..., description="Table name")
    columns: list[str] = Field(..., description="Column names")
    rows: list[list[Any]] = Field(..., description="Row data")
    total_rows: int = Field(..., description="Total number of rows returned")
    has_more: bool = Field(default=False, description="Whether more rows exist")


class ConnectionListResponse(BaseModel):
    """Response containing list of saved connections."""

    connections: list[DatabaseConnectionConfig] = Field(
        ..., description="List of saved connections"
    )
    active_connection_id: str | None = Field(
        default=None, description="ID of the currently active connection"
    )


# Chat Message DTOs
class Message(BaseModel):
    """Chat message model."""

    role: Literal["user", "assistant"] = Field(
        ..., description="Role of the message sender"
    )
    content: str = Field(..., description="Message content (supports markdown)")
    type: Literal["sql", "plain", "text_with_csv"] = Field(
        default="plain", description="Type of the message"
    )
    download_link: str | None = Field(
        default=None, description="Optional download link for results"
    )
    sql_query: str | None = Field(
        default=None, description="Generated SQL query (for debugging/transparency)"
    )
    preview_data: str | None = Field(
        default=None, description="Preview of CSV data (markdown table format, first 10 rows)"
    )


class MessagesRequest(BaseModel):
    """Request model for sending messages."""

    messages: list[Message] = Field(
        ..., description="List of messages in the conversation"
    )


class SqlRequest(BaseModel):
    """Request model for SQL execution."""

    sql: str = Field(..., description="SQL query to execute")


class ErrorResponse(BaseModel):
    """Error response model."""

    error: str = Field(..., description="Error message")
    detail: str | None = Field(default=None, description="Additional error details")
    status_code: int = Field(default=500, description="HTTP status code")


# WebSocket Notification DTOs
class TableChangeNotification(BaseModel):
    """WebSocket notification for table changes."""

    type: Literal["tables_added", "tables_removed", "scan_complete", "scan_error"] = Field(
        ..., description="Type of notification"
    )
    connection_id: str = Field(..., description="Connection identifier")
    tables: list[str] = Field(default_factory=list, description="Affected table names")
    message: str = Field(..., description="Human-readable message")
    timestamp: datetime = Field(
        default_factory=_utcnow, description="Notification timestamp"
    )


class ScanStatusResponse(BaseModel):
    """Response for scan status endpoint."""

    connection_id: str = Field(..., description="Connection identifier")
    if_active: bool = Field(..., description="Whether scanning is active")
    next_run_time: str | None = Field(
        default=None, description="Next scheduled scan time (ISO format)"
    )
    last_scan_time: str | None = Field(
        default=None, description="Last scan time (ISO format)"
    )
    interval_seconds: int = Field(..., description="Scan interval in seconds")


__all__ = [
    # Database Connection DTOs
    "DatabaseConnectionConfig",
    "ConnectionTestResponse",
    "TableInfo",
    "ColumnInfo",
    "TableDetails",
    "TablePreviewRequest",
    "TablePreviewResponse",
    "ConnectionListResponse",
    # Chat Message DTOs
    "Message",
    "MessagesRequest",
    "SqlRequest",
    "ErrorResponse",
    # WebSocket Notification DTOs
    "TableChangeNotification",
    "ScanStatusResponse",
]
