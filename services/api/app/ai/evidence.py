"""Evidence understanding: the second boundary between this API and the AI service.

When evidence is uploaded, this API stores it and then asks the AI service to
analyse it (OCR, vision, text). The AI service keeps its own results; this API
only tracks whether the analysis is processing, ready or failed, so the
evidence library can show it and a person can retry.

    provider.process(EvidenceRequest(...))   ->  None, or raises AiUnavailableError

MockEvidenceProcessor succeeds without doing anything, so the workflow runs
end to end before the AI service exists. HttpEvidenceProcessor calls the real
service. The choice is configuration (AI_EVIDENCE_PROVIDER).
"""

import logging
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

import httpx2
from pydantic import BaseModel

from app.ai.extraction import AI_TIMEOUT_SECONDS, AiUnavailableError

logger = logging.getLogger("subpay.api.ai")


class EvidenceRequest(BaseModel):
    evidence_id: UUID
    project_id: UUID
    evidence_type: str
    title: str
    description: str
    captured_at: datetime
    metadata: dict[str, Any]
    original_filename: str | None = None
    mime_type: str | None = None
    # Short-lived signed link the AI service can use to fetch the file. Null for a written note.
    document_url: str | None = None


class EvidenceProcessor(Protocol):
    def process(self, request: EvidenceRequest) -> None: ...


class MockEvidenceProcessor:
    """Stand-in for the AI service: accepts every record straight away."""

    def __init__(self, *, available: bool = True) -> None:
        self.available = available

    def process(self, request: EvidenceRequest) -> None:
        if not self.available:
            raise AiUnavailableError()


class HttpEvidenceProcessor:
    """Calls the AI service: POST {AI_SERVICE_URL}/ai/v1/evidence/{evidence_id}/understand."""

    def __init__(self, http: httpx2.Client, base_url: str) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")

    def process(self, request: EvidenceRequest) -> None:
        url = f"{self._base_url}/ai/v1/evidence/{request.evidence_id}/understand"
        try:
            response = self._http.post(
                url, json=request.model_dump(mode="json"), timeout=AI_TIMEOUT_SECONDS
            )
        except httpx2.HTTPError as exc:
            logger.error("AI service unreachable: %s", exc)
            raise AiUnavailableError() from exc
        if not response.is_success:
            logger.error("AI service answered %s for evidence understanding", response.status_code)
            raise AiUnavailableError()
