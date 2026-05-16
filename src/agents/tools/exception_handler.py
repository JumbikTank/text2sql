"""
Exception handler for mapping tool exceptions to user-friendly messages.
This module provides a centralized way to handle custom exceptions from the tools
and convert them into appropriate API responses.
"""

from typing import Dict, Any
from src.agents.tools.init_tools import (
    ToolException,
    VectorSearchException,
    SQLGenerationException,
    SQLExecutionException,
    NoRelevantTablesException,
    InvalidSQLException,
    DataConversionException,
    MissingContextException,
)


def handle_tool_exception(e: Exception) -> Dict[str, Any]:
    """
    Convert tool exceptions to user-friendly error responses.

    Args:
        e: The exception to handle

    Returns:
        A dictionary containing error information suitable for API responses
    """
    if isinstance(e, NoRelevantTablesException):
        return {
            "type": "error",
            "error": str(e),
            "error_code": "NO_RELEVANT_TABLES",
            "suggestion": "Try using more specific keywords or terms related to your database schema.",
        }

    elif isinstance(e, VectorSearchException):
        return {
            "type": "error",
            "error": str(e),
            "error_code": "VECTOR_SEARCH_FAILED",
            "suggestion": "The search service may be temporarily unavailable. Please try again in a moment.",
        }

    elif isinstance(e, SQLGenerationException):
        return {
            "type": "error",
            "error": str(e),
            "error_code": "SQL_GENERATION_FAILED",
            "suggestion": "Try breaking down your question into simpler parts or providing more context.",
        }

    elif isinstance(e, InvalidSQLException):
        return {
            "type": "error",
            "error": str(e),
            "error_code": "INVALID_SQL",
            "suggestion": "The system couldn't generate a valid query. Please rephrase your question.",
        }

    elif isinstance(e, SQLExecutionException):
        # Extract more specific error info if available
        error_msg = str(e)
        if "syntax error" in error_msg.lower():
            suggestion = (
                "The generated query has syntax issues. Try simplifying your question."
            )
        elif "timeout" in error_msg.lower():
            suggestion = (
                "The query is too complex. Try narrowing down your search criteria."
            )
        elif "permission" in error_msg.lower() or "denied" in error_msg.lower():
            suggestion = "You don't have permission to access this data. Contact your administrator."
        else:
            suggestion = (
                "Try rephrasing your question or breaking it into smaller parts."
            )

        return {
            "type": "error",
            "error": error_msg,
            "error_code": "SQL_EXECUTION_FAILED",
            "suggestion": suggestion,
        }

    elif isinstance(e, DataConversionException):
        return {
            "type": "error",
            "error": str(e),
            "error_code": "DATA_CONVERSION_FAILED",
            "suggestion": "The system couldn't format the results. Please try a simpler query.",
        }

    elif isinstance(e, MissingContextException):
        return {
            "type": "error",
            "error": str(e),
            "error_code": "MISSING_CONTEXT",
            "suggestion": "Start with an initial question before asking follow-up questions.",
        }

    elif isinstance(e, ToolException):
        # Generic tool exception
        return {
            "type": "error",
            "error": str(e),
            "error_code": "TOOL_ERROR",
            "suggestion": "An error occurred while processing your request. Please try again.",
        }

    else:
        # Unknown exception - log it and return generic error
        return {
            "type": "error",
            "error": "An unexpected error occurred while processing your request.",
            "error_code": "UNEXPECTED_ERROR",
            "suggestion": "Please try again later or contact support if the issue persists.",
            "details": str(e) if str(e) else "No additional details available",
        }


def create_error_response(
    exception: Exception, include_trace: bool = False
) -> Dict[str, Any]:
    """
    Create a standardized error response from an exception.

    Args:
        exception: The exception to convert
        include_trace: Whether to include stack trace (for debug mode)

    Returns:
        A standardized error response dictionary
    """
    response = handle_tool_exception(exception)

    if include_trace:
        import traceback

        response["trace"] = traceback.format_exc()

    return response


# Example usage in API endpoints
async def example_api_handler(request_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Example of how to use the exception handler in an API endpoint.
    """
    from src.common.logger import get_logger

    logger = get_logger(__name__)

    try:
        # Call the tool functions
        from src.agents.tools.init_tools import generate_sql_query

        result = await generate_sql_query(
            question=request_data.get("question", ""),
            model=request_data.get("model", "multilingual-e5-small"),
        )

        return result

    except ToolException as e:
        # Handle known tool exceptions
        logger.warning(f"Tool exception occurred: {e}")
        return create_error_response(e, include_trace=False)

    except Exception as e:
        # Handle unexpected exceptions
        logger.error(f"Unexpected error in API handler: {e}")
        logger.exception("Full traceback:")
        return create_error_response(e, include_trace=True)
