"""Factory for creating LLM providers."""

from typing import Any, Literal

from src.llm.base import BaseLLMProvider
from src.llm.providers.anthropic import AnthropicProvider
from src.llm.providers.google import GoogleProvider
from src.llm.providers.oci import OCIProvider
from src.llm.providers.ollama import OllamaProvider
from src.llm.providers.openai import OpenAIProvider

LLMProviderType = Literal["oci", "openai", "anthropic", "ollama", "google"]


class UnsupportedProviderError(Exception):
    """Raised when an unsupported LLM provider is requested."""

    pass


def create_llm_provider(
    provider_type: LLMProviderType,
    model_id: str,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    **kwargs: Any,
) -> BaseLLMProvider:
    """Create an LLM provider instance.

    Args:
        provider_type: Type of LLM provider ("oci", "openai", "anthropic", "ollama")
        model_id: Model identifier
        temperature: Sampling temperature (0.0-1.0)
        max_tokens: Maximum tokens in response
        **kwargs: Provider-specific parameters

    Returns:
        Configured LLM provider instance

    Raises:
        UnsupportedProviderError: If provider_type is not supported

    Examples:
        >>> # Create OCI provider
        >>> provider = create_llm_provider(
        ...     "oci",
        ...     model_id="cohere.command-r-plus",
        ...     compartment_id="ocid1.compartment...",
        ...     service_endpoint="https://...",
        ... )

        >>> # Create OpenAI provider
        >>> provider = create_llm_provider(
        ...     "openai",
        ...     model_id="gpt-4",
        ...     api_key="sk-...",
        ... )

        >>> # Create Anthropic provider
        >>> provider = create_llm_provider(
        ...     "anthropic",
        ...     model_id="claude-3-opus-20240229",
        ...     api_key="sk-ant-...",
        ... )

        >>> # Create Ollama provider (local)
        >>> provider = create_llm_provider(
        ...     "ollama",
        ...     model_id="llama3",
        ...     base_url="http://localhost:11434",
        ... )
    """
    providers: dict[LLMProviderType, type[BaseLLMProvider]] = {
        "oci": OCIProvider,
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "ollama": OllamaProvider,
        "google": GoogleProvider,
    }

    provider_class = providers.get(provider_type)
    if provider_class is None:
        raise UnsupportedProviderError(
            f"Unsupported provider: {provider_type}. "
            f"Supported providers: {', '.join(providers.keys())}"
        )

    return provider_class(
        model_id=model_id,
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs,
    )


__all__ = ["create_llm_provider", "LLMProviderType", "UnsupportedProviderError"]
