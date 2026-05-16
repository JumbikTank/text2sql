import sys
from typing import Any

from loguru import logger


def setup_logger(
    level: str = "INFO",
    serialize: bool = False,
    diagnose: bool = False,
) -> None:
    """Configure loguru logger with specified settings."""
    logger.remove()

    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        colorize=True,
        serialize=serialize,
        backtrace=True,
        diagnose=diagnose,
        enqueue=True,
    )


def get_logger(name: str | None = None) -> Any:
    """Get a logger instance with optional context binding."""
    if name:
        return logger.bind(name=name)
    return logger


__all__ = ["setup_logger", "get_logger", "logger"]
