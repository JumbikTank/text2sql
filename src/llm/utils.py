"""Utility functions for LLM providers."""

from typing import Any

from langchain_core.language_models import BaseChatModel

from src.common.settings import Settings
from src.llm.factory import create_llm_provider


def create_llm_from_settings(
    settings: Settings,
    temperature: float | None = None,
    max_tokens: int | None = None,
    for_agent: bool = False,
) -> BaseChatModel:
    """Create an LLM client from application settings.

    Args:
        settings: Application settings instance
        temperature: Override temperature (uses settings defaults if None)
        max_tokens: Override max tokens (uses settings defaults if None)
        for_agent: If True, uses agent-specific temperature and max_tokens from settings

    Returns:
        Configured LangChain BaseChatModel instance

    Raises:
        ValueError: If required settings are missing for the selected provider
    """
    # Use agent or client settings
    if for_agent:
        temp = temperature if temperature is not None else settings.temperature_agent
        tokens = max_tokens if max_tokens is not None else settings.max_tokens_agent
    else:
        temp = temperature if temperature is not None else settings.temperature_client
        tokens = max_tokens if max_tokens is not None else settings.max_tokens_client

    # Validate model_id
    if not settings.model_id:
        raise ValueError(
            "model_id is required in settings. "
            "Please set MODEL_ID environment variable or update settings."
        )

    # Build provider-specific kwargs
    kwargs: dict[str, Any] = {}
    provider = settings.llm_provider.lower()

    if provider == "oci":
        # OCI-specific configuration
        if not settings.compartment_id:
            raise ValueError(
                "compartment_id is required for OCI provider. "
                "Please set COMPARTMENT_ID environment variable."
            )

        kwargs.update(
            {
                "compartment_id": settings.compartment_id,
                "service_endpoint": settings.service_endpoint,
                "auth_file_location": settings.auth_file_location,
                "auth_profile": settings.auth_profile,
                "auth_type": settings.auth_type,
                "top_p": 1.0,
                "top_k": 1,
                "seed": 42,
            }
        )

    elif provider == "openai":
        # OpenAI-specific configuration
        kwargs.update(
            {
                "api_key": settings.openai_api_key,
                "base_url": settings.openai_base_url,
            }
        )

    elif provider == "anthropic":
        # Anthropic-specific configuration
        kwargs.update(
            {
                "api_key": settings.anthropic_api_key,
            }
        )

    elif provider == "ollama":
        # Ollama-specific configuration
        kwargs.update(
            {
                "base_url": settings.ollama_base_url,
            }
        )

    elif provider == "google":
        # Gemini-specific configuration
        kwargs.update(
            {
                "api_key": settings.google_api_key,
            }
        )

    else:
        raise ValueError(
            f"Unsupported LLM provider: {provider}. "
            f"Supported providers: oci, openai, anthropic, ollama, google"
        )

    # Create provider instance
    llm_provider = create_llm_provider(
        provider_type=provider,  # type: ignore
        model_id=settings.model_id,
        temperature=temp,
        max_tokens=tokens,
        **kwargs,
    )

    # Return the LangChain client
    return llm_provider.get_client()


__all__ = ["create_llm_from_settings"]
