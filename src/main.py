from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from litestar import Litestar, Request, Response, MediaType
from litestar.config.cors import CORSConfig
from litestar.di import Provide
from litestar.openapi import OpenAPIConfig
from litestar.static_files import create_static_files_router
from litestar.exceptions import HTTPException

from src.agents.services import MessageService
from src.api import api_router, health_router, mock_router, schema_router
from src.api.messages import provide_settings, provide_message_service
from src.api.websocket import websocket_handler, connection_manager
from src.common.error_handler import handle_exception
from src.common.logger import setup_logger, get_logger
from src.common.metadata_db import MetadataDB
from src.common.settings import get_settings
from src.services.embedding_service import EmbeddingService
from src.services.scanner_service import ScannerService
from src.services.scheduler_service import SchedulerService

# Get settings
settings = get_settings()

# Setup logging
setup_logger(
    level=settings.log_level,
    serialize=settings.log_serialize,
    diagnose=settings.log_diagnose,
)

# CORS configuration
#
# Guard against the spec-invalid combination of `allow_origins=["*"]` with
# `allow_credentials=true`, which browsers silently reject. If credentials are
# enabled, origins must be explicit.
_cors_origins = settings.cors_allow_origins
_cors_credentials = settings.cors_allow_credentials
if _cors_credentials and "*" in _cors_origins:
    logger_startup = get_logger(__name__)
    logger_startup.warning(
        "CORS allow_credentials=True is incompatible with allow_origins=['*']. "
        "Disabling credentials; set CORS_ALLOW_ORIGINS to an explicit list to re-enable."
    )
    _cors_credentials = False

cors_config = CORSConfig(
    allow_origins=_cors_origins,
    allow_credentials=_cors_credentials,
    allow_methods=["*"],
    allow_headers=settings.cors_allow_headers,
)

# OpenAPI configuration
openapi_config = (
    OpenAPIConfig(
        title=settings.openapi_title,
        version=settings.openapi_version,
    )
    if settings.openapi_enabled
    else None
)

# Static file serving for CSV downloads
csv_static_router = create_static_files_router(
    path="/files/csv", directories=[Path(settings.csv_export_path)], name="csv_files"
)

# Get module logger
logger = get_logger(__name__)

# Global service instances (initialized in lifespan)
metadata_db: MetadataDB | None = None
embedding_service: EmbeddingService | None = None
scanner_service: ScannerService | None = None
scheduler_service: SchedulerService | None = None


def get_scheduler_service() -> SchedulerService | None:
    """Get the global scheduler service instance."""
    return scheduler_service


def http_exception_handler(request: Request, exc: HTTPException) -> Response:
    """Custom exception handler to always return error details."""
    return Response(
        media_type=MediaType.JSON,
        content={"status_code": exc.status_code, "detail": exc.detail},
        status_code=exc.status_code,
    )


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncGenerator[None, None]:
    """Application lifespan context manager.

    Initializes and shuts down long-lived services.
    """
    global metadata_db, embedding_service, scanner_service, scheduler_service

    logger.info("Starting application services...")

    metadata_db = MetadataDB(settings)
    await metadata_db.bootstrap()

    embedding_service = EmbeddingService(metadata_engine=metadata_db.engine)

    scanner_service = ScannerService(
        settings=settings,
        embedding_service=embedding_service,
        notification_callback=connection_manager.broadcast_from_scanner,
    )

    scheduler_service = SchedulerService(
        settings=settings,
        scanner_service=scanner_service,
    )

    scheduler_service.start()
    logger.info("Scheduler service started")

    # MessageService is cached so the agent pipeline (LLM client, DB engine,
    # vector store, table descriptions) is built once and reused across requests.
    message_service = MessageService(
        settings,
        scanner_service=scanner_service,
        metadata_engine=metadata_db.engine,
        embedding_service=embedding_service,
    )

    app.state.metadata_db = metadata_db
    app.state.embedding_service = embedding_service
    app.state.scanner_service = scanner_service
    app.state.scheduler_service = scheduler_service
    app.state.message_service = message_service

    yield

    logger.info("Shutting down application services...")

    if scheduler_service:
        scheduler_service.stop()

    if scanner_service:
        await scanner_service.close()

    await message_service.close()

    if metadata_db:
        await metadata_db.close()

    logger.info("Application services shut down")


# Create application
app = Litestar(
    route_handlers=[
        health_router,
        api_router,
        mock_router,
        schema_router,
        csv_static_router,
        websocket_handler,
    ],
    cors_config=cors_config,
    openapi_config=openapi_config,
    dependencies={
        "settings": Provide(provide_settings, sync_to_thread=False),
        "message_service": Provide(provide_message_service, sync_to_thread=False),
    },
    lifespan=[lifespan],
    debug=settings.debug,
    exception_handlers={
        HTTPException: http_exception_handler,
        Exception: handle_exception,
    },
)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        workers=settings.workers if not settings.reload else 1,
        log_level=settings.log_level.lower(),
    )
