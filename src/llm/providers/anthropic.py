"""Anthropic (Claude) LLM provider."""

from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel

from src.llm.base import BaseLLMProvider


class AnthropicProvider(BaseLLMProvider):
    """Anthropic (Claude) LLM provider.

    Uses Anthropic's Claude API via langchain-anthropic.

    Additional kwargs:
        - api_key: Anthropic API key (can also use ANTHROPIC_API_KEY env var)
        - base_url: Custom API base URL
        - timeout: Request timeout in seconds
        - max_retries: Maximum number of retries for failed requests
        - top_p: Nucleus sampling parameter
        - top_k: Top-k sampling parameter
        - stop_sequences: List of sequences that will cause model to stop generating
    """

    def _create_client(self) -> BaseChatModel:
        """Create ChatAnthropic client.

        Returns:
            Configured ChatAnthropic instance.
        """
        # Extract Anthropic-specific parameters
        api_key = self.kwargs.get("api_key")
        base_url = self.kwargs.get("base_url")
        timeout = self.kwargs.get("timeout")
        max_retries = self.kwargs.get("max_retries", 2)

        # Model kwargs for generation parameters
        model_kwargs: dict[str, Any] = {}

        # Add optional parameters if provided
        if "top_p" in self.kwargs:
            model_kwargs["top_p"] = self.kwargs["top_p"]
        if "top_k" in self.kwargs:
            model_kwargs["top_k"] = self.kwargs["top_k"]
        if "stop_sequences" in self.kwargs:
            model_kwargs["stop_sequences"] = self.kwargs["stop_sequences"]

        return ChatAnthropic(
            model=self.model_id,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            **model_kwargs,
        )
