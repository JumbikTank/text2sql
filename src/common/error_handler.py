"""Error handling for the application."""

import traceback

from litestar import Request, Response
from litestar.exceptions import HTTPException, ValidationException
from litestar.status_codes import (
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_429_TOO_MANY_REQUESTS,
    HTTP_500_INTERNAL_SERVER_ERROR,
)
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.exc import (
    DatabaseError as SQLDatabaseError,
    IntegrityError,
    OperationalError,
)

from src.common.dto import ErrorResponse
from src.common.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BaseServiceError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)
from src.common.logger import get_logger

logger = get_logger(__name__)


def handle_exception(request: Request, exc: Exception) -> Response[ErrorResponse]:
    """Handle different types of exceptions and return appropriate responses."""

    error_id = id(exc)
    logger.error(
        f"Error {error_id} on {request.method} {request.url.path}: {exc}", exc_info=True
    )

    if isinstance(exc, BaseServiceError):
        return _handle_service_error(exc, error_id)

    elif isinstance(exc, HTTPException):
        return _handle_http_exception(exc, error_id)

    elif isinstance(exc, (ValidationException, PydanticValidationError)):
        return _handle_validation_error(exc, error_id)

    elif isinstance(exc, (SQLDatabaseError, OperationalError, IntegrityError)):
        return _handle_database_error(exc, error_id)

    elif isinstance(exc, FileNotFoundError):
        return _handle_file_not_found_error(exc, error_id)

    elif isinstance(exc, PermissionError):
        return _handle_permission_error(exc, error_id)

    elif isinstance(exc, ConnectionError):
        return _handle_connection_error(exc, error_id)

    elif isinstance(exc, TimeoutError):
        return _handle_timeout_error(exc, error_id)

    else:
        return _handle_unknown_error(exc, error_id)


def _handle_service_error(
    exc: BaseServiceError, error_id: int
) -> Response[ErrorResponse]:
    """Handle custom service errors."""
    status_code = HTTP_500_INTERNAL_SERVER_ERROR

    if isinstance(exc, ValidationError):
        status_code = HTTP_400_BAD_REQUEST
    elif isinstance(exc, NotFoundError):
        status_code = HTTP_404_NOT_FOUND
    elif isinstance(exc, RateLimitError):
        status_code = HTTP_429_TOO_MANY_REQUESTS
    elif isinstance(exc, (AuthenticationError, AuthorizationError)):
        status_code = HTTP_400_BAD_REQUEST

    return Response(
        content=ErrorResponse(
            error=exc.user_message,
            detail=f"Error reference: {error_id}",
            status_code=status_code,
        ),
        status_code=status_code,
    )


def _handle_http_exception(
    exc: HTTPException, error_id: int
) -> Response[ErrorResponse]:
    """Handle HTTP exceptions."""
    user_messages = {
        400: "Invalid request. Please check your input and try again.",
        401: "Authentication required. Please log in.",
        403: "Access denied. You don't have permission for this action.",
        404: "The requested resource was not found.",
        405: "This action is not allowed for this resource.",
        409: "There was a conflict with your request. Please try again.",
        413: "Your request is too large. Please reduce the size and try again.",
        422: "Invalid data provided. Please check your input.",
        429: "Too many requests. Please wait a moment before trying again.",
        500: "We're experiencing technical difficulties. Please try again later.",
        502: "Service temporarily unavailable. Please try again in a few minutes.",
        503: "Service temporarily unavailable. Please try again in a few minutes.",
    }

    user_message = user_messages.get(
        exc.status_code, "Something went wrong. Please try again later."
    )

    return Response(
        content=ErrorResponse(
            error=user_message,
            detail=f"Error reference: {error_id}",
            status_code=exc.status_code,
        ),
        status_code=exc.status_code,
    )


def _handle_validation_error(_: Exception, error_id: int) -> Response[ErrorResponse]:
    """Handle validation errors."""
    return Response(
        content=ErrorResponse(
            error="Invalid input provided. Please check your data and try again.",
            detail=f"Error reference: {error_id}",
            status_code=HTTP_400_BAD_REQUEST,
        ),
        status_code=HTTP_400_BAD_REQUEST,
    )


def _handle_database_error(exc: Exception, error_id: int) -> Response[ErrorResponse]:
    """Handle database-related errors."""
    if isinstance(exc, IntegrityError):
        user_message = "Data conflict detected. Please check your input and try again."
    else:
        user_message = (
            "Database service is temporarily unavailable. Please try again in a moment."
        )

    return Response(
        content=ErrorResponse(
            error=user_message,
            detail=f"Error reference: {error_id}",
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        ),
        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _handle_file_not_found_error(
    _: FileNotFoundError, error_id: int
) -> Response[ErrorResponse]:
    """Handle file not found errors."""
    return Response(
        content=ErrorResponse(
            error="A required resource is missing. Please contact support.",
            detail=f"Error reference: {error_id}",
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        ),
        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _handle_permission_error(
    _: PermissionError, error_id: int
) -> Response[ErrorResponse]:
    """Handle permission errors."""
    return Response(
        content=ErrorResponse(
            error="Service configuration issue. Please contact support.",
            detail=f"Error reference: {error_id}",
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        ),
        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _handle_connection_error(
    _: ConnectionError, error_id: int
) -> Response[ErrorResponse]:
    """Handle connection errors."""
    return Response(
        content=ErrorResponse(
            error="Unable to connect to external services. Please try again later.",
            detail=f"Error reference: {error_id}",
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        ),
        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _handle_timeout_error(_: TimeoutError, error_id: int) -> Response[ErrorResponse]:
    """Handle timeout errors."""
    return Response(
        content=ErrorResponse(
            error="Request timed out. Please try again with a simpler query.",
            detail=f"Error reference: {error_id}",
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        ),
        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _handle_unknown_error(exc: Exception, error_id: int) -> Response[ErrorResponse]:
    """Handle unknown/unexpected errors."""
    logger.critical(f"Unhandled exception {error_id}: {type(exc).__name__}: {exc}")
    logger.critical(f"Traceback: {traceback.format_exc()}")

    return Response(
        content=ErrorResponse(
            error="We're experiencing unexpected technical difficulties. Please try again later.",
            detail=f"Error reference: {error_id}",
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        ),
        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
    )


__all__ = ["handle_exception", "BaseServiceError"]
