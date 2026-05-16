from functools import lru_cache
from typing import Literal

from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    model_config = SettingsConfigDict(
        env_file=ENV_PATH,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application settings
    app_name: str = Field(default="Text2SQL Backend", description="Application name")
    app_version: str = Field(default="0.1.0", description="Application version")
    debug: bool = Field(default=False, description="Debug mode")
    environment: Literal["development", "staging", "production"] = Field(
        default="development", description="Environment name"
    )

    # Server settings
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, description="Server port")
    reload: bool = Field(default=False, description="Enable auto-reload")
    workers: int = Field(default=1, description="Number of workers")

    # Logging settings
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Logging level"
    )
    log_serialize: bool = Field(default=False, description="Serialize logs to JSON")
    log_diagnose: bool = Field(default=False, description="Enable diagnostic mode")

    # CORS settings.
    # Note: browsers reject `Access-Control-Allow-Credentials: true` combined with
    # `Access-Control-Allow-Origin: *`, so the default below keeps credentials off.
    # For production, set explicit origins and enable credentials if needed.
    cors_allow_origins: list[str] = Field(
        default=["*"], description="Allowed CORS origins"
    )
    cors_allow_credentials: bool = Field(
        default=False, description="Allow credentials in CORS"
    )
    cors_allow_methods: list[str] = Field(
        default=["*"], description="Allowed CORS methods"
    )
    cors_allow_headers: list[str] = Field(
        default=["*"], description="Allowed CORS headers"
    )

    # OpenAPI settings
    openapi_enabled: bool = Field(default=True, description="Enable OpenAPI docs")
    openapi_title: str = Field(default="Text2SQL API", description="OpenAPI title")
    openapi_version: str = Field(default="1.0.0", description="OpenAPI version")
    openapi_path: str = Field(default="/schema", description="OpenAPI schema path")

    # API settings
    api_prefix: str = Field(default="/api", description="API route prefix")
    api_timeout: int = Field(default=30, description="API request timeout in seconds")

    # Database settings
    username: str = Field(description="Database username")
    password: str = Field(description="Database password")
    db_host: str = Field(description="Database host")
    db_port: int = Field(default=3306, description="Database port")
    database: str = Field(description="Database name")
    database_echo: bool = Field(default=False, description="Echo database queries")

    # Metadata DB (Text2SQL-owned Postgres+pgvector store for table embeddings).
    # All per-connection `notes` rows live here so user DBs aren't required to
    # have pgvector or DDL privileges.
    metadata_db_host: str = Field(
        default="localhost", description="Metadata DB host"
    )
    metadata_db_port: int = Field(
        default=5434, description="Metadata DB port"
    )
    metadata_db_user: str = Field(
        default="text2sql", description="Metadata DB user"
    )
    metadata_db_password: str = Field(
        default="text2sql", description="Metadata DB password"
    )
    metadata_db_name: str = Field(
        default="text2sql_metadata", description="Metadata DB database name"
    )

    # AI/LLM settings
    llm_provider: str = Field(
        default="oci",
        description="LLM provider to use (oci, openai, anthropic, ollama)",
    )
    model_id: str | None = Field(
        default=None, description="LLM model identifier"
    )
    temperature_client: float = Field(
        default=0, description="LLM temperature for response randomness (0.0-1.0)"
    )
    max_tokens_client: int = Field(
        default=4096, description="Maximum tokens in LLM response"
    )
    temperature_agent: float = Field(
        default=0, description="LLM temperature for response randomness (0.0-1.0)"
    )
    max_tokens_agent: int = Field(
        default=16000, description="Maximum tokens in LLM response"
    )

    # OpenAI settings (when llm_provider="openai")
    openai_api_key: str | None = Field(
        default=None, description="OpenAI API key"
    )
    openai_base_url: str | None = Field(
        default=None, description="OpenAI API base URL (for custom endpoints)"
    )

    # Anthropic settings (when llm_provider="anthropic")
    anthropic_api_key: str | None = Field(
        default=None, description="Anthropic API key"
    )

    # Ollama settings (when llm_provider="ollama")
    ollama_base_url: str = Field(
        default="http://localhost:11434", description="Ollama server URL"
    )

    # Google Gemini settings (when llm_provider="google")
    google_api_key: str | None = Field(
        default=None, description="Google AI Studio / Gemini API key"
    )

    # File export settings
    csv_export_path: str = Field(
        default="./tmp/csv", description="Directory path for CSV file exports"
    )
    csv_download_base_url: str = Field(
        default="http://localhost:18001/files/csv",
        description="Base URL for CSV file downloads",
    )

    # Credential storage settings
    credential_storage_path: str = Field(
        default="./data/connections.enc",
        description="Path to encrypted credential storage file",
    )
    credential_encryption_key: str | None = Field(
        default=None,
        description="Fernet encryption key for credential storage",
    )
    use_saved_connection: bool = Field(
        default=False,
        description="Use saved connection instead of env vars for database",
    )

    # OCI Configuration (for future use)
    compartment_id: str | None = Field(
        default=None, description="OCI compartment ID for AI services"
    )
    auth_file_location: str = Field(
        default="../.oci/config", description="Path to OCI authentication config file"
    )
    service_endpoint: str | None = Field(
        default=None, description="OCI Generative AI service endpoint URL"
    )
    auth_profile: str = Field(
        default="DEFAULT", description="OCI authentication profile name"
    )
    auth_type: str = Field(default="API_KEY", description="OCI authentication method")

    # Scanner settings
    scanner_enabled: bool = Field(
        default=True,
        description="Enable automatic table scanning",
    )
    scanner_default_interval: int = Field(
        default=60,
        description="Default scanning interval in seconds",
    )

    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.environment == "development"

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


__all__ = ["Settings", "get_settings"]
