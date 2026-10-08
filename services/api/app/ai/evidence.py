"""Evidence understanding: the second boundary between this API and the AI service.

When evidence is uploaded, this API stores it and then asks the AI service to
analyse it (OCR, vision, text). The AI service keeps its own results; this API
only tracks whether the analysis is processing, ready or failed, so the
evidence library can show it and a person can retry.

    provider.understand(EvidenceRequest(...)) -> EvidenceUnderstandingResult

MockEvidenceProcessor succeeds without doing anything, so the workflow runs
end to end before the AI service exists. HttpEvidenceProcessor calls the real
service. The choice is configuration (AI_EVIDENCE_PROVIDER).
"""

import logging
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

import httpx2
from pydantic import BaseModel, Field, ValidationError

from app.ai.extraction import AI_TIMEOUT_SECONDS, AiUnavailableError
from app.ai.matching import EvidenceSignals

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


class EvidenceUnderstandingResult(BaseModel):
    evidence_id: UUID
    signals: EvidenceSignals
    confidence: float = Field(ge=0, le=1)


class EvidenceProcessor(Protocol):
    def understand(self, request: EvidenceRequest) -> EvidenceUnderstandingResult: ...

    def process(self, request: EvidenceRequest) -> None: ...


class MockEvidenceProcessor:
    """Stand-in for the AI service: accepts every record straight away."""

    def __init__(self, *, available: bool = True) -> None:
        self.available = available

    def understand(self, request: EvidenceRequest) -> EvidenceUnderstandingResult:
        if not self.available:
            raise AiUnavailableError()
        text = f"{request.title} {request.description}".strip()
        metadata_location = request.metadata.get("location")
        return EvidenceUnderstandingResult(
            evidence_id=request.evidence_id,
            confidence=0.82 if text or request.document_url else 0.45,
            signals=EvidenceSignals(
                objects=_objects(text, request.evidence_type),
                activities=_activities(text),
                extracted_text=text or None,
                location=str(metadata_location) if metadata_location else None,
                date=request.captured_at,
                other_signals={
                    "evidence_type": request.evidence_type,
                    "source": request.metadata.get("source"),
                    "tags": request.metadata.get("tags", []),
                    "original_filename": request.original_filename,
                    "mime_type": request.mime_type,
                },
            ),
        )

    def process(self, request: EvidenceRequest) -> None:
        self.understand(request)


class HttpEvidenceProcessor:
    """Calls the AI service: POST {AI_SERVICE_URL}/ai/v1/evidence/{evidence_id}/understand."""

    def __init__(self, http: httpx2.Client, base_url: str) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")

    def understand(self, request: EvidenceRequest) -> EvidenceUnderstandingResult:
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
        try:
            result = EvidenceUnderstandingResult.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            logger.error("AI service returned an unreadable evidence understanding result: %s", exc)
            raise AiUnavailableError() from exc
        if result.evidence_id != request.evidence_id:
            logger.error("AI service answered evidence understanding for a different record")
            raise AiUnavailableError()
        return result

    def process(self, request: EvidenceRequest) -> None:
        self.understand(request)


def _activities(text: str) -> list[str]:
    lowered = text.lower()
    found: list[str] = []
    for keyword, label in [
        ("poured", "concrete poured"),
        ("pour", "concrete pour"),
        ("installed", "installed"),
        ("installation", "installation"),
        ("complete", "completed work"),
        ("delay", "delay"),
        ("extra", "additional work"),
        ("variation", "variation mentioned"),
    ]:
        if keyword in lowered:
            found.append(label)
    return found


def _objects(text: str, evidence_type: str) -> list[str]:
    lowered = f"{text} {evidence_type}".lower()
    return [
        label
        for keyword, label in [
            ("formwork", "formwork"),
            ("concrete", "concrete"),
            ("slab", "slab"),
            ("photo", "photo"),
            ("docket", "docket"),
            ("invoice", "invoice"),
        ]
        if keyword in lowered
    ]
