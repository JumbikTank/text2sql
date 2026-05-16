"""Schema browsing and connection management API endpoints."""

from litestar import Response, get, post, put, delete, Router, Request
from litestar.exceptions import HTTPException
from litestar.status_codes import HTTP_200_OK, HTTP_201_CREATED, HTTP_204_NO_CONTENT

from src.common.dto import (
    ConnectionListResponse,
    ConnectionTestResponse,
    DatabaseConnectionConfig,
    ScanStatusResponse,
    TableDetails,
    TableInfo,
    TablePreviewRequest,
    TablePreviewResponse,
)
from src.common.logger import get_logger
from src.common.settings import Settings
from src.services.connection_service import ConnectionService, ConnectionServiceError
from src.services.scanner_service import ScanResult
from src.services.scheduler_service import SchedulerService, SchedulerServiceError

logger = get_logger(__name__)


def _get_connection_service(settings: Settings) -> ConnectionService:
    """Create a connection service instance."""
    return ConnectionService(settings)


def _get_scheduler_service(request: Request) -> SchedulerService | None:
    """Get the scheduler service from app state."""
    return getattr(request.app.state, "scheduler_service", None)


# Connection Management Endpoints

@post("/connections/test")
async def test_connection(
    data: DatabaseConnectionConfig,
    settings: Settings,
) -> Response[ConnectionTestResponse]:
    """Test a database connection without saving it."""
    service = _get_connection_service(settings)
    result = await service.test_connection(data)
    return Response(result, status_code=HTTP_200_OK)


@get("/connections")
async def list_connections(
    settings: Settings,
) -> Response[ConnectionListResponse]:
    """List all saved database connections."""
    try:
        service = _get_connection_service(settings)
        result = service.list_connections()
        return Response(result, status_code=HTTP_200_OK)
    except ConnectionServiceError as e:
        raise HTTPException(status_code=500, detail=str(e))


@post("/connections")
async def save_connection(
    data: DatabaseConnectionConfig,
    settings: Settings,
) -> Response[DatabaseConnectionConfig]:
    """Save a new database connection."""
    try:
        service = _get_connection_service(settings)
        result = service.save_connection(data)
        return Response(result, status_code=HTTP_201_CREATED)
    except ConnectionServiceError as e:
        raise HTTPException(status_code=500, detail=str(e))


@get("/connections/{connection_id:str}")
async def get_connection(
    connection_id: str,
    settings: Settings,
) -> Response[DatabaseConnectionConfig]:
    """Get a specific connection by ID."""
    try:
        service = _get_connection_service(settings)
        result = service.get_connection(connection_id)
        return Response(result, status_code=HTTP_200_OK)
    except ConnectionServiceError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@put("/connections/{connection_id:str}")
async def update_connection(
    connection_id: str,
    data: DatabaseConnectionConfig,
    settings: Settings,
) -> Response[DatabaseConnectionConfig]:
    """Update an existing connection."""
    try:
        service = _get_connection_service(settings)
        result = service.update_connection(connection_id, data)
        return Response(result, status_code=HTTP_200_OK)
    except ConnectionServiceError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@delete("/connections/{connection_id:str}")
async def delete_connection(
    connection_id: str,
    settings: Settings,
) -> Response[None]:
    """Delete a connection."""
    try:
        service = _get_connection_service(settings)
        service.delete_connection(connection_id)
        return Response(None, status_code=HTTP_204_NO_CONTENT)
    except ConnectionServiceError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@post("/connections/{connection_id:str}/activate")
async def activate_connection(
    connection_id: str,
    settings: Settings,
    request: Request,
) -> Response[None]:
    """Set a connection as the active connection and start background scanning."""
    try:
        service = _get_connection_service(settings)
        service.set_active_connection(connection_id)

        # Start background scanning for this connection
        scheduler = _get_scheduler_service(request)
        if scheduler:
            try:
                scheduler.add_scan_job(connection_id)
                logger.info(f"Started background scanning for connection {connection_id}")
            except SchedulerServiceError as e:
                logger.warning(f"Could not start scanner for {connection_id}: {e}")

        # Run an initial synchronous scan so embeddings for this connection
        # exist in the metadata DB before the first chat query. This is a
        # no-op when the scheduler already populated them.
        scanner_service = getattr(request.app.state, "scanner_service", None)
        if scanner_service:
            try:
                await scanner_service.scan_connection(connection_id)
                logger.info(f"Initial scan completed for connection {connection_id}")
            except Exception as e:
                logger.warning(f"Initial scan failed for {connection_id}: {e}")

        return Response(None, status_code=HTTP_200_OK)
    except ConnectionServiceError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@post("/connections/{connection_id:str}/scan")
async def trigger_scan(
    connection_id: str,
    settings: Settings,
    request: Request,
) -> Response[ScanResult]:
    """Trigger an immediate scan for a connection.

    This manually triggers a table scan and embedding generation for the connection.
    """
    # Verify connection exists
    try:
        service = _get_connection_service(settings)
        service.get_connection(connection_id)
    except ConnectionServiceError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))

    # Get scanner service and run scan
    scanner_service = getattr(request.app.state, "scanner_service", None)
    if not scanner_service:
        raise HTTPException(
            status_code=503,
            detail="Scanner service not available",
        )

    try:
        result = await scanner_service.scan_connection(connection_id)
        return Response(result, status_code=HTTP_200_OK)
    except Exception as e:
        logger.error(f"Scan failed for {connection_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@get("/connections/{connection_id:str}/scan-status")
async def get_scan_status(
    connection_id: str,
    settings: Settings,
    request: Request,
) -> Response[ScanStatusResponse]:
    """Get the scan status for a connection.

    Returns information about the scheduled scan job including last/next run times.
    """
    # Verify connection exists
    try:
        service = _get_connection_service(settings)
        service.get_connection(connection_id)
    except ConnectionServiceError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))

    scheduler = _get_scheduler_service(request)
    if not scheduler:
        return Response(
            ScanStatusResponse(
                connection_id=connection_id,
                if_active=False,
                interval_seconds=settings.scanner_default_interval,
            ),
            status_code=HTTP_200_OK,
        )

    status = scheduler.get_job_status(connection_id)
    if status:
        return Response(
            ScanStatusResponse(
                connection_id=connection_id,
                if_active=status["if_active"],
                next_run_time=status["next_run_time"],
                last_scan_time=status["last_scan_time"],
                interval_seconds=status["interval_seconds"],
            ),
            status_code=HTTP_200_OK,
        )

    return Response(
        ScanStatusResponse(
            connection_id=connection_id,
            if_active=False,
            interval_seconds=settings.scanner_default_interval,
        ),
        status_code=HTTP_200_OK,
    )


# Schema Browsing Endpoints

@get("/schema/tables")
async def list_tables(
    settings: Settings,
    schema_name: str = "public",
) -> Response[list[TableInfo]]:
    """List tables in the specified schema."""
    try:
        service = _get_connection_service(settings)
        result = await service.get_tables(schema_name)
        return Response(result, status_code=HTTP_200_OK)
    except ConnectionServiceError as e:
        if "no active connection" in str(e).lower():
            raise HTTPException(
                status_code=400,
                detail="No active connection. Please configure and activate a connection first.",
            )
        raise HTTPException(status_code=500, detail=str(e))


@get("/schema/tables/{table_name:str}")
async def get_table_details(
    table_name: str,
    settings: Settings,
    schema_name: str = "public",
) -> Response[TableDetails]:
    """Get detailed information about a table including columns."""
    try:
        service = _get_connection_service(settings)
        result = await service.get_table_details(table_name, schema_name)
        return Response(result, status_code=HTTP_200_OK)
    except ConnectionServiceError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        if "no active connection" in str(e).lower():
            raise HTTPException(
                status_code=400,
                detail="No active connection. Please configure and activate a connection first.",
            )
        if "invalid" in str(e).lower():
            raise HTTPException(status_code=400, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@post("/schema/preview")
async def preview_table(
    data: TablePreviewRequest,
    settings: Settings,
) -> Response[TablePreviewResponse]:
    """Preview table data (first N rows)."""
    try:
        service = _get_connection_service(settings)
        result = await service.preview_table(
            data.table_name,
            data.schema_name,
            data.limit,
        )
        return Response(result, status_code=HTTP_200_OK)
    except ConnectionServiceError as e:
        if "no active connection" in str(e).lower():
            raise HTTPException(
                status_code=400,
                detail="No active connection. Please configure and activate a connection first.",
            )
        if "invalid" in str(e).lower():
            raise HTTPException(status_code=400, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# Create router for schema endpoints
schema_router = Router(
    path="/api",
    route_handlers=[
        test_connection,
        list_connections,
        save_connection,
        get_connection,
        update_connection,
        delete_connection,
        activate_connection,
        trigger_scan,
        get_scan_status,
        list_tables,
        get_table_details,
        preview_table,
    ],
    tags=["Schema"],
)

__all__ = ["schema_router"]
