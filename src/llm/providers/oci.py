"""Oracle Cloud Infrastructure (OCI) Generative AI provider."""

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_oci.chat_models import ChatOCIGenAI

from src.llm.base import BaseLLMProvider


class OCIProvider(BaseLLMProvider):
    """OCI Generative AI LLM provider.

    Uses Oracle Cloud Infrastructure's Generative AI service via langchain-oci.

    Additional kwargs:
        - service_endpoint: OCI service endpoint URL
        - compartment_id: OCI compartment ID
        - auth_file_location: Path to OCI config file (default: ~/.oci/config)
        - auth_profile: OCI profile name (default: DEFAULT)
        - auth_type: Authentication type (default: API_KEY)
        - top_p: Nucleus sampling parameter
        - top_k: Top-k sampling parameter
        - seed: Random seed for deterministic generation
    """

    def _create_client(self) -> BaseChatModel:
        """Create ChatOCIGenAI client.

        Returns:
            Configured ChatOCIGenAI instance.
        """
        # Extract OCI-specific parameters
        service_endpoint = self.kwargs.get("service_endpoint")
        compartment_id = self.kwargs.get("compartment_id")
        auth_file_location = self.kwargs.get("auth_file_location", "~/.oci/config")
        auth_profile = self.kwargs.get("auth_profile", "DEFAULT")
        auth_type = self.kwargs.get("auth_type", "API_KEY")

        # Model kwargs for generation parameters
        model_kwargs: dict[str, Any] = {
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        # Add optional parameters if provided
        if "top_p" in self.kwargs:
            model_kwargs["top_p"] = self.kwargs["top_p"]
        if "top_k" in self.kwargs:
            model_kwargs["top_k"] = self.kwargs["top_k"]
        if "seed" in self.kwargs:
            model_kwargs["seed"] = self.kwargs["seed"]

        return ChatOCIGenAI(
            model_id=self.model_id,
            service_endpoint=service_endpoint,
            compartment_id=compartment_id,
            model_kwargs=model_kwargs,
            auth_file_location=auth_file_location,
            auth_profile=auth_profile,
            auth_type=auth_type,
        )
