#!/usr/bin/env python
"""Run the application."""

import uvicorn

from src.common.settings import get_settings

if __name__ == "__main__":
    settings = get_settings()

    # Use import string when reload is enabled, app object otherwise
    if settings.reload:
        uvicorn.run(
            "src.main:app",
            host=settings.host,
            port=settings.port,
            reload=settings.reload,
            workers=1,  # reload mode only supports 1 worker
            log_level=settings.log_level.lower(),
        )
    else:
        from src.main import app

        uvicorn.run(
            app,
            host=settings.host,
            port=settings.port,
            workers=settings.workers,
            log_level=settings.log_level.lower(),
        )
