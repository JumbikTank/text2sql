"""OpenAI LLM provider."""

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from src.llm.base import BaseLLMProvider


class OpenAIProvider(BaseLLMProvider):
    """OpenAI LLM provider.

    Uses OpenAI's API via langchain-openai.

    Additional kwargs:
        - api_key: OpenAI API key (can also use OPENAI_API_KEY env var)
        - base_url: Custom API base URL (for OpenAI-compatible endpoints)
        - organization: OpenAI organization ID
        - timeout: Request timeout in seconds
        - max_retries: Maximum number of retries for failed requests
        - top_p: Nucleus sampling parameter
        - frequency_penalty: Frequency penalty parameter
        - presence_penalty: Presence penalty parameter
        - seed: Random seed for deterministic generation
    """

    def _create_client(self) -> BaseChatModel:
        """Create ChatOpenAI client.

        Returns:
            Configured ChatOpenAI instance.
        """
        # Extract OpenAI-specific parameters
        api_key = self.kwargs.get("api_key")
        base_url = self.kwargs.get("base_url")
        organization = self.kwargs.get("organization")
        timeout = self.kwargs.get("timeout")
        max_retries = self.kwargs.get("max_retries", 2)

        # Model kwargs for generation parameters
        model_kwargs: dict[str, Any] = {}

        # Add optional parameters if provided
        if "top_p" in self.kwargs:
            model_kwargs["top_p"] = self.kwargs["top_p"]
        if "frequency_penalty" in self.kwargs:
            model_kwargs["frequency_penalty"] = self.kwargs["frequency_penalty"]
        if "presence_penalty" in self.kwargs:
            model_kwargs["presence_penalty"] = self.kwargs["presence_penalty"]
        if "seed" in self.kwargs:
            model_kwargs["seed"] = self.kwargs["seed"]

        # Build ChatOpenAI init parameters
        init_params: dict[str, Any] = {
            "model": self.model_id,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "max_retries": max_retries,
        }

        # Add optional parameters only if they're not None
        if api_key is not None:
            init_params["api_key"] = api_key
        if base_url is not None:
            init_params["base_url"] = base_url
        if organization is not None:
            init_params["organization"] = organization
        if timeout is not None:
            init_params["timeout"] = timeout
        if model_kwargs:
            init_params["model_kwargs"] = model_kwargs

        return ChatOpenAI(**init_params)
