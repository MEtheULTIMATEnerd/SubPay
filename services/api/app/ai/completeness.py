"""Evidence support completeness: API-side boundary to the AI service."""

import logging
from typing import Literal, Protocol
from uuid import UUID

import httpx2
from pydantic import BaseModel, Field, ValidationError

from app.ai.extraction import AI_TIMEOUT_SECONDS, AiUnavailableError
from app.ai.matching import MatchSuggestion

logger = logging.getLogger("subpay.api.ai")

CompletenessStatus = Literal["strong", "partial", "weak", "missing"]


class CompletenessRequest(BaseModel):
    contract_item_id: UUID
    matches: list[MatchSuggestion] = Field(default_factory=list)


class CompletenessResult(BaseModel):
    contract_item_id: UUID
    status: CompletenessStatus
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=1000)


class CompletenessProvider(Protocol):
    def assess(self, request: CompletenessRequest) -> CompletenessResult: ...


class MockCompletenessProvider:
    """Deterministic evidence support assessment.

    This assesses AI evidence support only. It does not replace Rehan's
    human-confirmed readiness semantics.
    """

    def __init__(self, *, available: bool = True) -> None:
        self.available = available

    def assess(self, request: CompletenessRequest) -> CompletenessResult:
        if not self.available:
            raise AiUnavailableError()
        if not request.matches:
            return CompletenessResult(
                contract_item_id=request.contract_item_id,
                status="missing",
                confidence=0.9,
                reason="No supporting evidence suggestions were supplied for this contract item.",
            )
        best = sorted(request.matches, key=lambda match: match.confidence, reverse=True)[0]
        status = _status(best.assessment, bool(best.missing_evidence))
        return CompletenessResult(
            contract_item_id=request.contract_item_id,
            status=status,
            confidence=best.confidence,
            reason=(
                "Evidence support is based on the strongest AI suggestion. "
                f"Best assessment: {best.assessment}."
            ),
        )


class HttpCompletenessProvider:
    """Calls the AI service: POST {AI_SERVICE_URL}/ai/v1/completeness."""

    def __init__(self, http: httpx2.Client, base_url: str) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")

    def assess(self, request: CompletenessRequest) -> CompletenessResult:
        url = f"{self._base_url}/ai/v1/completeness"
        try:
            response = self._http.post(
                url, json=request.model_dump(mode="json"), timeout=AI_TIMEOUT_SECONDS
            )
        except httpx2.HTTPError as exc:
            logger.error("AI service unreachable for completeness: %s", exc)
            raise AiUnavailableError() from exc
        if not response.is_success:
            logger.error("AI service answered %s for completeness", response.status_code)
            raise AiUnavailableError()
        try:
            result = CompletenessResult.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            logger.error("AI service returned an unreadable completeness result: %s", exc)
            raise AiUnavailableError() from exc
        if result.contract_item_id != request.contract_item_id:
            logger.error("AI service answered completeness for a different contract item")
            raise AiUnavailableError()
        return result


def _status(assessment: str, has_missing_evidence: bool) -> CompletenessStatus:
    if assessment == "strong" and not has_missing_evidence:
        return "strong"
    if assessment in {"strong", "partial"}:
        return "partial"
    return "weak"
