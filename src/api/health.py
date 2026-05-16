from litestar import Response, get
from litestar.status_codes import HTTP_200_OK

from src.common.settings import Settings


@get("/health")
async def health_check(settings: Settings) -> Response[dict]:
    """Health check endpoint for Docker and monitoring."""
    return Response(
        content={
            "status": "healthy",
            "service": settings.app_name,
            "version": settings.app_version,
            "environment": settings.environment,
        },
        status_code=HTTP_200_OK,
    )


__all__ = ["health_check"]
