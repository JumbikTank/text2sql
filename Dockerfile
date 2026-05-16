# Multi-stage build for optimized Python application
FROM python:3.13-slim AS base

# Builder stage
FROM base AS builder

# Install build dependencies for packages that need compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy uv binary from official image (using specific version for reproducibility)
COPY --from=ghcr.io/astral-sh/uv:0.5.20 /uv /bin/uv

# Set environment variables for optimal builds
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Set working directory
WORKDIR /app

# Install dependencies first (better layer caching)
COPY pyproject.toml uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Copy application code
COPY . ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Production stage
FROM base

# Copy uv for runtime (needed for uv run)
COPY --from=ghcr.io/astral-sh/uv:0.5.20 /uv /bin/uv

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    UV_COMPILE_BYTECODE=1

# Create non-root user with home directory
RUN groupadd -r appuser && useradd -r -g appuser -m -d /home/appuser appuser

# Set working directory
WORKDIR /app

# Copy application and virtual environment from builder
COPY --from=builder --chown=appuser:appuser /app /app

# Create necessary directories with proper permissions
RUN mkdir -p /home/appuser/.cache/uv /app/tmp/csv && \
    chown -R appuser:appuser /home/appuser/.cache /app/tmp

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run application
CMD ["uv", "run", "python", "run.py"]