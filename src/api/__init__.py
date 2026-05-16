from litestar import Router

from src.api.health import health_check
from src.api.messages import send_messages
from src.api.mock import mock_execute_sql, mock_send_messages
from src.api.schema import schema_router
from src.api.sql import execute_sql
from src.api.websocket import websocket_handler, connection_manager

# Health endpoint (no prefix)
health_router = Router(
    path="/",
    route_handlers=[health_check],
    tags=["Health"],
)

# Real endpoints
api_router = Router(
    path="/api",
    route_handlers=[
        send_messages,
        execute_sql,
    ],
    tags=["API"],
)

# Mock endpoints
mock_router = Router(
    path="/api",
    route_handlers=[
        mock_send_messages,
        mock_execute_sql,
    ],
    tags=["Mock API"],
)

__all__ = [
    "health_router",
    "api_router",
    "mock_router",
    "schema_router",
    "websocket_handler",
    "connection_manager",
]
