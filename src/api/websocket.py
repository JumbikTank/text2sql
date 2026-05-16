"""WebSocket handler for real-time notifications."""

import asyncio
from datetime import UTC, datetime

from litestar import WebSocket, websocket
from litestar.exceptions import WebSocketDisconnect

from src.common.dto import TableChangeNotification
from src.common.logger import get_logger

logger = get_logger(__name__)


class ConnectionManager:
    """Manages WebSocket connections for real-time notifications."""

    def __init__(self) -> None:
        # Map of connection_id -> set of WebSocket connections
        self._connections: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, connection_id: str) -> None:
        """Register a new WebSocket connection.

        Args:
            websocket: The WebSocket instance
            connection_id: The database connection ID to subscribe to
        """
        await websocket.accept()

        async with self._lock:
            if connection_id not in self._connections:
                self._connections[connection_id] = set()
            self._connections[connection_id].add(websocket)

        logger.info(
            f"WebSocket connected for connection {connection_id}, "
            f"total clients: {len(self._connections.get(connection_id, set()))}"
        )

    async def disconnect(self, websocket: WebSocket, connection_id: str) -> None:
        """Unregister a WebSocket connection.

        Args:
            websocket: The WebSocket instance to remove
            connection_id: The database connection ID
        """
        async with self._lock:
            if connection_id in self._connections:
                self._connections[connection_id].discard(websocket)
                if not self._connections[connection_id]:
                    del self._connections[connection_id]

        logger.info(f"WebSocket disconnected for connection {connection_id}")

    async def broadcast(
        self,
        connection_id: str,
        notification: TableChangeNotification,
    ) -> None:
        """Broadcast a notification to all clients subscribed to a connection.

        Args:
            connection_id: The database connection ID
            notification: The notification to broadcast
        """
        async with self._lock:
            clients = self._connections.get(connection_id, set()).copy()

        if not clients:
            logger.debug(f"No clients connected for {connection_id}, skipping broadcast")
            return

        message = notification.model_dump_json()
        disconnected = []

        for client in clients:
            try:
                await client.send_text(message)
            except Exception as e:
                logger.warning(f"Failed to send to client: {e}")
                disconnected.append(client)

        # Clean up disconnected clients
        if disconnected:
            async with self._lock:
                for client in disconnected:
                    if connection_id in self._connections:
                        self._connections[connection_id].discard(client)

        logger.debug(
            f"Broadcast to {len(clients) - len(disconnected)} clients "
            f"for connection {connection_id}"
        )

    async def broadcast_from_scanner(
        self,
        notification_type: str,
        connection_id: str,
        tables: list[str],
        message: str,
    ) -> None:
        """Callback method for ScannerService to send notifications.

        This matches the NotificationCallback signature expected by ScannerService.

        Args:
            notification_type: Type of notification (tables_added, tables_removed, etc.)
            connection_id: The connection identifier
            tables: List of affected table names
            message: Human-readable message
        """
        notification = TableChangeNotification(
            type=notification_type,  # type: ignore
            connection_id=connection_id,
            tables=tables,
            message=message,
            timestamp=datetime.now(UTC),
        )
        await self.broadcast(connection_id, notification)

    def get_client_count(self, connection_id: str) -> int:
        """Get the number of connected clients for a connection.

        Args:
            connection_id: The database connection ID

        Returns:
            Number of connected WebSocket clients
        """
        return len(self._connections.get(connection_id, set()))

    def get_all_connection_ids(self) -> list[str]:
        """Get all connection IDs with active WebSocket clients.

        Returns:
            List of connection IDs
        """
        return list(self._connections.keys())


# Global connection manager instance
connection_manager = ConnectionManager()


@websocket("/ws/{connection_id:str}")
async def websocket_handler(socket: WebSocket, connection_id: str) -> None:
    """WebSocket endpoint for receiving table change notifications.

    Clients connect to /ws/{connection_id} to receive notifications about
    table changes for that database connection.

    Args:
        socket: The WebSocket connection
        connection_id: The database connection ID to subscribe to
    """
    await connection_manager.connect(socket, connection_id)

    try:
        while True:
            # Keep connection alive, handle any incoming messages
            data = await socket.receive_text()
            # Clients can send ping messages to keep connection alive
            if data == "ping":
                await socket.send_text("pong")
            elif data == "status":
                # Send current status
                count = connection_manager.get_client_count(connection_id)
                await socket.send_text(f'{{"type": "status", "clients": {count}}}')
    except WebSocketDisconnect:
        logger.debug(f"WebSocket client disconnected for {connection_id}")
    except Exception as e:
        logger.error(f"WebSocket error for {connection_id}: {e}")
    finally:
        await connection_manager.disconnect(socket, connection_id)


__all__ = ["websocket_handler", "connection_manager", "ConnectionManager"]
