# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Text2SQL Backend is a Python-based API service that implements a natural language to SQL query pipeline using multiple LLM providers (OCI, OpenAI, Anthropic, Ollama) and LangChain/LangGraph. The system converts user questions into SQL queries, executes them against relational databases, and provides natural language responses. Features universal LLM provider support and extensible architecture.

## Development Commands

### Package Management (uv only)
```bash
# Install dependencies
uv sync

# Add new dependency
uv add <package>

# Remove dependency
uv remove <package>

# Run Python scripts
uv run python run.py

# Run tests
uv run pytest

# Run linting
uv run ruff check . --fix
uv run ruff format .

# Type checking
uv run pyright
```

### Docker Operations
```bash
# Using Makefile (preferred)
make build          # Build Docker image
make up             # Start production mode (port 8001)
make dev            # Start development mode with live reload
make down           # Stop containers
make test-api       # Test API endpoints
make logs           # View logs
make shell          # Open shell in container

# Using manage.sh script
./manage.sh build   # Build Docker image
./manage.sh up      # Start production
./manage.sh dev     # Development mode
./manage.sh test    # Test endpoints
./manage.sh status  # Check status

# Direct Docker commands
docker compose build
docker compose up -d
docker compose down
```

## Architecture

### API Layer (Litestar Framework)
```
src/
├── api/
│   ├── health.py        # Health check endpoint
│   ├── messages.py      # /api/messages endpoint (AI chat)
│   ├── sql.py          # /api/sql endpoint (SQL execution)
│   └── mock.py         # Mock endpoints for testing
├── common/
│   ├── dto.py          # Pydantic models (Message, MessagesRequest, SqlRequest)
│   ├── settings.py     # Application settings (pydantic-settings)
│   └── logger.py       # Loguru configuration
├── llm/
│   ├── base.py         # Abstract LLM provider interface
│   ├── factory.py      # LLM provider factory
│   ├── utils.py        # Helper functions
│   └── providers/      # Provider implementations (OCI, OpenAI, Anthropic, Ollama)
└── main.py             # Litestar app initialization
```

### Agent Pipeline (LangGraph)
```
src/agents/
├── states.py               # Graph state definitions
├── table_relationships.py  # Table relationship analysis
├── columns_analyzer.py     # Column analysis for SQL generation
└── tools/
    ├── text_to_sql_generator.py  # Main orchestrator
    ├── required_tables_searcher.py # Vector search for tables
    ├── sql_creator.py             # LLM-powered SQL generation
    ├── sql_executor.py            # Database query execution
    ├── df_to_text_converter.py    # Result formatting
    └── prompt_templates.py        # System prompts
```

### Pipeline Flow
1. **User Message** → API receives chat messages array
2. **Vector Search** → `VectorStore.search()` finds relevant tables using MySQL HeatWave ML_EMBED
3. **Table Filtering** → LLM filters tables based on relevance
4. **SQL Generation** → `SQLCreator.create_sql()` generates SQL with safety guardrails
5. **Execution** → `SQLExecutor.query()` runs read-only queries
6. **Response** → `DataFrameToTextConverter.answer()` formats results as natural language

### Key Technical Details

**Database Integration:**
- MySQL HeatWave with vector search capabilities
- Vector similarity using `DISTANCE()` and `ML_EMBED_ROW()` functions
- Read-only SQL validation (blocks DROP, DELETE, UPDATE, INSERT, ALTER, etc.)
- Async SQLAlchemy with asyncmy driver

**LLM Provider Support:**
- **Universal LLM abstraction** - Single interface for multiple providers
- **OCI Generative AI** - Oracle Cloud (langchain-oci)
- **OpenAI** - GPT models (langchain-openai)
- **Anthropic** - Claude models (langchain-anthropic)
- **Ollama** - Local models (langchain-ollama)
- Provider selection via `LLM_PROVIDER` environment variable
- Easy to add new providers by implementing `BaseLLMProvider`

**API Endpoints (Port 8001):**
- `GET /health` - Health check
- `POST /api/messages` - Process chat messages (501 - not implemented)
- `POST /api/sql` - Execute SQL directly (501 - not implemented)
- `POST /api/mock/messages` - Mock chat responses for testing
- `POST /api/mock/sql` - Mock SQL execution for testing
- OpenAPI docs at `/docs`, schema at `/schema/openapi.json`

**Async Patterns:**
- All database operations use async/await
- LLM calls wrapped in `asyncio.to_thread()` for OCI SDK
- Litestar async handlers throughout

## Environment Configuration

### Required Environment Variables
```bash
# LLM Configuration (choose one provider)
LLM_PROVIDER=oci  # Options: oci, openai, anthropic, ollama
MODEL_ID=<your-model-id>

# For OCI provider
COMPARTMENT_ID=<your-compartment-id>
AUTH_FILE_LOCATION=~/.oci/config
AUTH_PROFILE=DEFAULT
SERVICE_ENDPOINT=<oci-endpoint-url>

# For OpenAI provider
OPENAI_API_KEY=<your-api-key>
# OPENAI_BASE_URL=<custom-endpoint>  # Optional, for custom endpoints

# For Anthropic provider
ANTHROPIC_API_KEY=<your-api-key>

# For Ollama provider (local models)
OLLAMA_BASE_URL=http://localhost:11434

# Database
USERNAME=<db-user>
PASSWORD=<db-password>
DB_HOST=<db-host>
DB_PORT=3306
DATABASE=<db-name>
DATABASE_ECHO=false

# Application
ENVIRONMENT=development
DEBUG=false
LOG_LEVEL=INFO
PORT=8000  # Internal container port
```

### Docker Configuration
- Container runs as non-root user (appuser)
- Virtual environment at `/app/.venv`
- Source code mounted at `/app/src` for development
- uv cache at `/home/appuser/.cache/uv`
- Health checks every 30s

## Dependencies

Core framework stack:
- **litestar** - Async API framework
- **langchain/langgraph** - LLM orchestration
- **langchain-oci** - OCI Generative AI integration
- **langchain-openai** - OpenAI integration
- **langchain-anthropic** - Anthropic (Claude) integration
- **langchain-ollama** - Ollama (local models) integration
- **sqlalchemy[asyncio]** with **asyncmy** - Async MySQL
- **pandas** - Data manipulation
- **pydantic/pydantic-settings** - Data validation and settings

## Code Conventions

- Python 3.13+ with modern type hints
- async/await for all I/O operations
- Pydantic models for all DTOs
- Dependency injection via Litestar DI
- Error handling with retry mechanisms for LLM calls
- Read-only SQL validation before execution
- Loguru for structured logging

## Adding New LLM Providers

To add support for a new LLM provider:

1. **Create provider implementation** in `src/llm/providers/your_provider.py`:
```python
from langchain_core.language_models import BaseChatModel
from src.llm.base import BaseLLMProvider

class YourProvider(BaseLLMProvider):
    def _create_client(self) -> BaseChatModel:
        # Initialize your LangChain chat model
        from langchain_yourprovider import ChatYourProvider

        return ChatYourProvider(
            model=self.model_id,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            api_key=self.kwargs.get("api_key"),
            # Add provider-specific parameters
        )
```

2. **Register in factory** in `src/llm/factory.py`:
```python
from src.llm.providers.your_provider import YourProvider

providers: dict[LLMProviderType, type[BaseLLMProvider]] = {
    "oci": OCIProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "ollama": OllamaProvider,
    "yourprovider": YourProvider,  # Add here
}
```

3. **Add settings** in `src/common/settings.py`:
```python
# YourProvider settings
yourprovider_api_key: str | None = Field(
    default=None, description="YourProvider API key"
)
```

4. **Update utils** in `src/llm/utils.py`:
```python
elif provider == "yourprovider":
    kwargs.update({
        "api_key": settings.yourprovider_api_key,
        # Add other provider-specific settings
    })
```

5. **Add dependency** in `pyproject.toml`:
```toml
dependencies = [
    ...
    "langchain-yourprovider>=0.1.0",
]
```
