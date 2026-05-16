"""Base LLM provider interface."""

from abc import ABC, abstractmethod
from typing import Any

from langchain_core.language_models import BaseChatModel


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers.

    This class defines the interface that all LLM providers must implement,
    enabling easy swapping between different LLM backends (OCI, OpenAI, Anthropic, Ollama, etc.).
    """

    def __init__(
        self,
        model_id: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> None:
        """Initialize the LLM provider.

        Args:
            model_id: Model identifier (e.g., "gpt-4", "claude-3-opus", "llama3")
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Maximum tokens in response
            **kwargs: Additional provider-specific parameters
        """
        self.model_id = model_id
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.kwargs = kwargs
        self._client: BaseChatModel | None = None

    @abstractmethod
    def _create_client(self) -> BaseChatModel:
        """Create and return the LangChain chat model instance.

        Returns:
            A LangChain BaseChatModel instance configured for this provider.
        """
        pass

    def get_client(self) -> BaseChatModel:
        """Get or create the LangChain chat model client.

        Returns:
            The configured LangChain chat model instance.
        """
        if self._client is None:
            self._client = self._create_client()
        return self._client

    @property
    def provider_name(self) -> str:
        """Get the provider name.

        Returns:
            The name of the LLM provider (e.g., "oci", "openai", "anthropic").
        """
        return self.__class__.__name__.replace("Provider", "").lower()

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"model_id={self.model_id!r}, "
            f"temperature={self.temperature}, "
            f"max_tokens={self.max_tokens})"
        )
