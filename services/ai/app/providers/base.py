"""Model/provider abstractions for the AI service.

The service layer depends on these protocols rather than any particular model
vendor. Real OpenAI, Qwen, Anthropic, local, or other adapters can be added
later without changing the API routes.
"""

from typing import Protocol


class LLMProvider(Protocol):
    def complete(self, prompt: str) -> str: ...


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]: ...


class VisionProvider(Protocol):
    def describe(self, *, document_url: str | None, text_hint: str = "") -> list[str]: ...

