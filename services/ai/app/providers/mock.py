"""Deterministic mock model providers.

These classes intentionally avoid external API calls and paid model services.
They make Phase A repeatable while preserving the provider seams needed for
real implementations later.
"""

import hashlib


class MockLLMProvider:
    def complete(self, prompt: str) -> str:
        normalized = " ".join(prompt.lower().split())
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
        return f"mock-llm:{digest}"


class MockEmbeddingProvider:
    def embed(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.lower().encode("utf-8")).digest()
        return [round(byte / 255, 6) for byte in digest[:8]]


class MockVisionProvider:
    def describe(self, *, document_url: str | None, text_hint: str = "") -> list[str]:
        text = text_hint.lower()
        objects: list[str] = []
        for keyword, label in [
            ("formwork", "formwork"),
            ("conduit", "electrical conduit"),
            ("cable tray", "cable tray"),
            ("switchboard", "switchboard"),
            ("concrete", "concrete"),
            ("docket", "delivery docket"),
            ("photo", "site photo"),
        ]:
            if keyword in text:
                objects.append(label)
        if document_url and not objects:
            objects.append("source document")
        return objects
