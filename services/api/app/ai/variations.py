"""Potential variation detection: API-side boundary to the AI service."""

import logging
import re
from typing import Protocol
from uuid import UUID

import httpx2
from pydantic import BaseModel, Field, StrictBool, ValidationError

from app.ai.extraction import AI_TIMEOUT_SECONDS, AiUnavailableError
from app.ai.matching import EvidenceSignals, MatchSuggestion

logger = logging.getLogger("subpay.api.ai")


class VariationDetectionRequest(BaseModel):
    evidence_id: UUID
    signals: EvidenceSignals
    matches: list[MatchSuggestion] = Field(default_factory=list)


class VariationDetectionResult(BaseModel):
    potential_variation: StrictBool
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=1000)
    related_evidence_ids: list[UUID] = Field(default_factory=list)
    review_required: StrictBool


class VariationProvider(Protocol):
    def detect(self, request: VariationDetectionRequest) -> VariationDetectionResult: ...


class MockVariationProvider:
    """Deterministic review flag for potential variations."""

    def __init__(self, *, available: bool = True) -> None:
        self.available = available

    def detect(self, request: VariationDetectionRequest) -> VariationDetectionResult:
        if not self.available:
            raise AiUnavailableError()
        text = " ".join(
            [
                request.signals.extracted_text or "",
                " ".join(request.signals.activities),
                " ".join(request.signals.objects),
            ]
        )
        best_confidence = max((match.confidence for match in request.matches), default=0)
        flag = best_confidence < 0.85 and bool(_CHANGE_WORDS.search(text))
        return VariationDetectionResult(
            potential_variation=flag,
            confidence=0.72 if flag else 0.5,
            reason=(
                "Evidence describes additional or changed work with no strong "
                "matching contract line."
                if flag
                else "No potential variation language was detected, or a strong "
                "contract match exists."
            ),
            related_evidence_ids=[request.evidence_id] if flag else [],
            review_required=flag,
        )


class HttpVariationProvider:
    """Calls the AI service: POST {AI_SERVICE_URL}/ai/v1/variations/detect."""

    def __init__(self, http: httpx2.Client, base_url: str) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")

    def detect(self, request: VariationDetectionRequest) -> VariationDetectionResult:
        url = f"{self._base_url}/ai/v1/variations/detect"
        try:
            response = self._http.post(
                url, json=request.model_dump(mode="json"), timeout=AI_TIMEOUT_SECONDS
            )
        except httpx2.HTTPError as exc:
            logger.error("AI service unreachable for variation detection: %s", exc)
            raise AiUnavailableError() from exc
        if not response.is_success:
            logger.error("AI service answered %s for variation detection", response.status_code)
            raise AiUnavailableError()
        try:
            result = VariationDetectionResult.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            logger.error("AI service returned an unreadable variation result: %s", exc)
            raise AiUnavailableError() from exc
        expected = {request.evidence_id}
        if result.related_evidence_ids and not set(result.related_evidence_ids).issubset(expected):
            logger.error("AI service answered variation result for different evidence")
            raise AiUnavailableError()
        return result


_CHANGE_WORDS = re.compile(
    r"\b(additional|extra|latent|unforeseen|changed|not on (the )?drawings|variation|instructed)\b",
    re.IGNORECASE,
)
