"""Ollama (local LLM) provider."""

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_ollama import ChatOllama

from src.llm.base import BaseLLMProvider


class OllamaProvider(BaseLLMProvider):
    """Ollama LLM provider for local models.

    Uses locally-hosted Ollama models via langchain-ollama.

    Additional kwargs:
        - base_url: Ollama server URL (default: http://localhost:11434)
        - timeout: Request timeout in seconds
        - top_p: Nucleus sampling parameter
        - top_k: Top-k sampling parameter
        - repeat_penalty: Penalty for repeated tokens
        - seed: Random seed for deterministic generation
        - num_ctx: Context window size
        - num_gpu: Number of GPU layers to use
        - num_thread: Number of threads for CPU inference
    """

    def _create_client(self) -> BaseChatModel:
        """Create ChatOllama client.

        Returns:
            Configured ChatOllama instance.
        """
        # Extract Ollama-specific parameters
        base_url = self.kwargs.get("base_url", "http://localhost:11434")
        timeout = self.kwargs.get("timeout")

        # Model kwargs for generation parameters
        model_kwargs: dict[str, Any] = {}

        # Add optional parameters if provided
        if "top_p" in self.kwargs:
            model_kwargs["top_p"] = self.kwargs["top_p"]
        if "top_k" in self.kwargs:
            model_kwargs["top_k"] = self.kwargs["top_k"]
        if "repeat_penalty" in self.kwargs:
            model_kwargs["repeat_penalty"] = self.kwargs["repeat_penalty"]
        if "seed" in self.kwargs:
            model_kwargs["seed"] = self.kwargs["seed"]
        if "num_ctx" in self.kwargs:
            model_kwargs["num_ctx"] = self.kwargs["num_ctx"]
        if "num_gpu" in self.kwargs:
            model_kwargs["num_gpu"] = self.kwargs["num_gpu"]
        if "num_thread" in self.kwargs:
            model_kwargs["num_thread"] = self.kwargs["num_thread"]

        return ChatOllama(
            model=self.model_id,
            temperature=self.temperature,
            num_predict=self.max_tokens,  # Ollama uses num_predict instead of max_tokens
            base_url=base_url,
            timeout=timeout,
            **model_kwargs,
        )
