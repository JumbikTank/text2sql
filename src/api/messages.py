from litestar import Request, Response, post

from src.agents.services import MessageService
from src.common.dto import Message, MessagesRequest
from src.common.logger import get_logger
from src.common.settings import Settings, get_settings

logger = get_logger(__name__)


def provide_settings() -> Settings:
    """Dependency provider for settings."""
    return get_settings()


def provide_message_service(request: Request) -> MessageService:
    """Provide the app-scoped MessageService from Litestar app state.

    The service is built once in the lifespan and lazily initializes the
    agent pipeline on first use (and when the active connection changes).
    """
    service = getattr(request.app.state, "message_service", None)
    if service is None:
        # Should only happen if lifespan hasn't run (e.g. in some tests).
        service = MessageService(get_settings())
        request.app.state.message_service = service
    return service


@post("/messages")
async def send_messages(
    data: MessagesRequest,
    message_service: MessageService,
) -> Response[Message]:
    logger.info(f"Received {len(data.messages)} messages")
    response_message = await message_service.process_messages(data.messages)
    logger.info(
        f"Response: type={response_message.type}, "
        f"content_len={len(response_message.content)}, "
        f"has_sql={response_message.sql_query is not None}"
    )
    return Response(response_message)


__all__ = [
    "send_messages",
    "provide_settings",
    "provide_message_service",
]
