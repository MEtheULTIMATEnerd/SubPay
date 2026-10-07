"""Evidence-to-contract matching: API-side boundary to the AI service.

The application API owns evidence, contract items, match persistence and human
confirmation. The AI service only suggests candidate links with confidence and
an explanation. These shapes match docs/api-contracts.md, section 6.
"""

import logging
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID

import httpx2
from pydantic import BaseModel, Field, ValidationError

from app.ai.extraction import AI_TIMEOUT_SECONDS, AiUnavailableError

logger = logging.getLogger("subpay.api.ai")

Assessment = Literal["strong", "partial", "weak"]


class EvidenceSignals(BaseModel):
    objects: list[str] = Field(default_factory=list)
    activities: list[str] = Field(default_factory=list)
    extracted_text: str | None = None
    location: str | None = None
    date: datetime | None = None
    other_signals: dict[str, Any] = Field(default_factory=dict)


class MatchingContractItem(BaseModel):
    contract_item_id: UUID
    item_code: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=1, max_length=2000)
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = None
    amount: float | None = Field(default=None, ge=0)


class MatchingRequest(BaseModel):
    evidence_id: UUID
    signals: EvidenceSignals
    contract_items: list[MatchingContractItem]


class MatchSuggestion(BaseModel):
    contract_item_id: UUID
    confidence: float = Field(ge=0, le=1)
    assessment: Assessment
    reason: str = Field(min_length=1, max_length=1000)
    missing_evidence: list[str] = Field(default_factory=list)


class MatchingResult(BaseModel):
    evidence_id: UUID
    matches: list[MatchSuggestion]


class MatchingProvider(Protocol):
    def match(self, request: MatchingRequest) -> MatchingResult: ...


class MockMatchingProvider:
    """Deterministic stand-in for candidate match generation.

    Matching uses token overlap between evidence signals and contract item text.
    A candidate is returned when overlap is at least 0.25. Confidence is a
    placeholder score in the 0.40-0.95 range, not a calibrated probability.
    """

    def __init__(self, *, available: bool = True) -> None:
        self.available = available

    def match(self, request: MatchingRequest) -> MatchingResult:
        if not self.available:
            raise AiUnavailableError()
        evidence_text = " ".join(
            [
                request.signals.extracted_text or "",
                request.signals.location or "",
                " ".join(request.signals.objects),
                " ".join(request.signals.activities),
            ]
        )
        evidence_tokens = set(_tokens(evidence_text))
        scored = []
        for item in request.contract_items:
            item_tokens = _tokens(f"{item.item_code} {item.description} {item.unit or ''}")
            hits = [token for token in item_tokens if token in evidence_tokens]
            score = len(hits) / len(item_tokens) if item_tokens else 0
            if score >= 0.25:
                scored.append((item, hits, score))
        scored.sort(key=lambda entry: entry[2], reverse=True)
        return MatchingResult(
            evidence_id=request.evidence_id,
            matches=[
                MatchSuggestion(
                    contract_item_id=item.contract_item_id,
                    confidence=round(0.4 + 0.55 * score, 2),
                    assessment=_assessment(0.4 + 0.55 * score),
                    reason=(
                        f"Evidence signals overlap with {item.item_code} "
                        f"{item.description}: {', '.join(hits)}."
                    ),
                    missing_evidence=_missing_evidence(0.4 + 0.55 * score),
                )
                for item, hits, score in scored[:3]
            ],
        )


class HttpMatchingProvider:
    """Calls the AI service: POST {AI_SERVICE_URL}/ai/v1/matches."""

    def __init__(self, http: httpx2.Client, base_url: str) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")

    def match(self, request: MatchingRequest) -> MatchingResult:
        url = f"{self._base_url}/ai/v1/matches"
        try:
            response = self._http.post(
                url, json=request.model_dump(mode="json"), timeout=AI_TIMEOUT_SECONDS
            )
        except httpx2.HTTPError as exc:
            logger.error("AI service unreachable for matching: %s", exc)
            raise AiUnavailableError() from exc
        if not response.is_success:
            logger.error("AI service answered %s for evidence matching", response.status_code)
            raise AiUnavailableError()
        try:
            result = MatchingResult.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            logger.error("AI service returned an unreadable matching result: %s", exc)
            raise AiUnavailableError() from exc
        if result.evidence_id != request.evidence_id:
            logger.error("AI service answered matching for a different evidence record")
            raise AiUnavailableError()
        return result


_STOP = {"a", "an", "and", "at", "by", "for", "from", "in", "is", "of", "on", "the", "to", "with"}


def _tokens(text: str) -> list[str]:
    normalized = "".join(char.lower() if char.isalnum() else " " for char in text)
    return sorted(
        {word.rstrip("s") for word in normalized.split() if len(word) > 1 and word not in _STOP}
    )


def _assessment(confidence: float) -> Assessment:
    if confidence >= 0.85:
        return "strong"
    if confidence >= 0.7:
        return "partial"
    return "weak"


def _missing_evidence(confidence: float) -> list[str]:
    if confidence >= 0.85:
        return []
    if confidence >= 0.7:
        return ["quantity confirmation"]
    return ["photo or docket confirming the work"]
