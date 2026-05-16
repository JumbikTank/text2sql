"""Custom exception classes for the application."""


class BaseServiceError(Exception):
    """Base exception for all service-level errors."""

    def __init__(
        self,
        message: str,
        user_message: str | None = None,
        error_code: str | None = None,
    ):
        super().__init__(message)
        self.user_message = (
            user_message
            or "I'm experiencing technical difficulties. Please try again later."
        )
        self.error_code = error_code or "INTERNAL_ERROR"


class ConfigurationError(BaseServiceError):
    """Raised when service configuration is invalid."""

    def __init__(self, message: str):
        super().__init__(
            message,
            "The service is not properly configured. Please contact support.",
            "CONFIGURATION_ERROR",
        )


class DatabaseError(BaseServiceError):
    """Raised when database operations fail."""

    def __init__(self, message: str):
        super().__init__(
            message,
            "I'm having trouble accessing the database. Please try again in a moment.",
            "DATABASE_ERROR",
        )


class AIServiceError(BaseServiceError):
    """Raised when AI service operations fail."""

    def __init__(self, message: str):
        super().__init__(
            message,
            "I'm having trouble processing your request right now. Please try again.",
            "AI_SERVICE_ERROR",
        )


class ValidationError(BaseServiceError):
    """Raised when input validation fails."""

    def __init__(self, message: str, user_message: str | None = None):
        super().__init__(
            message,
            user_message or "Please check your input and try again.",
            "VALIDATION_ERROR",
        )


class RateLimitError(BaseServiceError):
    """Raised when rate limits are exceeded."""

    def __init__(self, message: str):
        super().__init__(
            message,
            "You're sending requests too quickly. Please wait a moment before trying again.",
            "RATE_LIMIT_ERROR",
        )


class NotFoundError(BaseServiceError):
    """Raised when requested resource is not found."""

    def __init__(self, message: str, resource_type: str = "resource"):
        super().__init__(
            message,
            f"The requested {resource_type} could not be found.",
            "NOT_FOUND_ERROR",
        )


class AuthenticationError(BaseServiceError):
    """Raised when authentication fails."""

    def __init__(self, message: str):
        super().__init__(
            message,
            "Authentication failed. Please check your credentials.",
            "AUTHENTICATION_ERROR",
        )


class AuthorizationError(BaseServiceError):
    """Raised when authorization fails."""

    def __init__(self, message: str):
        super().__init__(
            message,
            "You don't have permission to access this resource.",
            "AUTHORIZATION_ERROR",
        )


__all__ = [
    "BaseServiceError",
    "ConfigurationError",
    "DatabaseError",
    "AIServiceError",
    "ValidationError",
    "RateLimitError",
    "NotFoundError",
    "AuthenticationError",
    "AuthorizationError",
]
