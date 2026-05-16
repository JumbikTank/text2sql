"""Google Gemini LLM provider."""

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI

from src.llm.base import BaseLLMProvider


class GoogleProvider(BaseLLMProvider):
    """Google Gemini LLM provider via langchain-google-genai.

    Additional kwargs:
        - api_key: Google AI Studio API key (also reads GOOGLE_API_KEY env var)
        - top_p: Nucleus sampling parameter
        - top_k: Top-k sampling parameter
        - timeout: Request timeout in seconds
        - max_retries: Maximum number of retries for failed requests
    """

    def _create_client(self) -> BaseChatModel:
        api_key = self.kwargs.get("api_key")
        timeout = self.kwargs.get("timeout")
        max_retries = self.kwargs.get("max_retries", 2)

        extra: dict[str, Any] = {}
        if "top_p" in self.kwargs:
            extra["top_p"] = self.kwargs["top_p"]
        if "top_k" in self.kwargs:
            extra["top_k"] = self.kwargs["top_k"]

        return ChatGoogleGenerativeAI(
            model=self.model_id,
            temperature=self.temperature,
            max_output_tokens=self.max_tokens,
            google_api_key=api_key,
            timeout=timeout,
            max_retries=max_retries,
            **extra,
        )
