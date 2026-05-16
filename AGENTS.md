# Agent Guidelines for Text2SQL Backend

## Build/Lint/Test Commands
- **Install deps**: `uv sync`
- **Run app**: `uv run python run.py`  
- **Run tests**: `uv run python test_api.py` (single test file)
- **Lint**: `uv run ruff check .` / `uv run ruff check . --fix`
- **Format**: `uv run ruff format .`
- **Type check**: `uv run pyright`
- **Docker**: `make build`, `make up`, `make dev`, `make test-api`

## Code Style
- **Package manager**: ONLY use `uv` (never pip)
- **Types**: Python 3.13+, async/await, type hints required
- **Naming**: snake_case functions/vars, PascalCase classes, UPPER_SNAKE constants
- **Imports**: `from src.module import Class` pattern, grouped by stdlib/3rd-party/local
- **Error handling**: Use async patterns, wrap OCI calls in `asyncio.to_thread()`
- **Models**: Pydantic with Field descriptions, use `__all__` exports
- **SQL**: Read-only validation, async SQLAlchemy with asyncmy
- **API**: Litestar endpoints, Response types, dependency injection
- **Logging**: Loguru for structured output

Always follow existing patterns in codebase.