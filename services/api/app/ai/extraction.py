"""Contract extraction: the boundary between this API and the AI service.

This API owns the workflow around extraction (store the document, start
processing, save the items, let a person review them). The AI service owns
the intelligence. They meet at ExtractionProvider:

    result = provider.extract(ExtractionRequest(...))   ->  ExtractionResult

MockExtractionProvider is a deterministic stand-in so the rest of the app can
be built and demonstrated without the AI service. HttpExtractionProvider
calls the real service. Swapping one for the other is a configuration change
(AI_EXTRACTION_PROVIDER); nothing else in the API changes.

The shapes here are the contract agreed in docs/api-contracts.md, section 6.
"""

import logging
import re
from datetime import date
from typing import Protocol
from uuid import UUID

import httpx2
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger("subpay.api.ai")

AI_UNAVAILABLE_MESSAGE = "AI analysis unavailable. Retry, or continue reviewing manually."
AI_TIMEOUT_SECONDS = 120.0


class AiUnavailableError(Exception):
    """The AI service could not produce a usable answer. Safe to show `str(exc)` to a user."""

    def __init__(self, message: str = AI_UNAVAILABLE_MESSAGE) -> None:
        super().__init__(message)


class ExtractionRequest(BaseModel):
    contract_id: UUID
    original_filename: str
    mime_type: str
    # Short-lived signed link the AI service can use to fetch the document.
    document_url: str | None = None


class ExtractedItem(BaseModel):
    """One claim line item as the AI read it.

    Only item_code, description and confidence are guaranteed. Everything else may be null.
    """

    item_code: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=1, max_length=2000)
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = None
    rate: float | None = Field(default=None, ge=0)
    amount: float | None = Field(default=None, ge=0)
    conditions: str | None = None
    notice_requirement: str | None = None
    due_date: date | None = None
    confidence: float = Field(ge=0, le=1)
    source_reference: str | None = None


class ExtractionResult(BaseModel):
    contract_id: UUID
    items: list[ExtractedItem]


class ExtractionProvider(Protocol):
    def extract(self, request: ExtractionRequest) -> ExtractionResult: ...


# code, description, quantity, unit, rate, amount, confidence, notice requirement
_Row = tuple[str, str, float | None, str | None, float | None, float | None, float, str | None]

_FITOUT_SCHEDULE: list[_Row] = [
    ("4.2", "Electrical conduit installation", 120, "m", 45, 5400, 0.91, None),
    ("4.3", "Cable tray installation", 80, "m", 60, 4800, 0.88, None),
    ("4.5", "Switchboard installation", 1, "item", 12500, 12500, 0.84,
     "Notify builder 5 days before energisation"),
    ("6.1", "Lighting fit-off", None, None, None, 7600, 0.67, None),
]  # fmt: skip

_FORMWORK_SCHEDULE: list[_Row] = [
    ("1.1", "Preliminaries and site establishment", 1, "item", 4500, 4500, 0.82, None),
    ("2.1", "Formwork, slab edges", 180, "m²", 75, 13500, 0.90, None),
    ("2.2", "Formwork, columns", 96, "m²", 95, 9120, 0.87, None),
    ("3.1", "Concrete supply and place", 110, "m³", 245, 26950, 0.86,
     "Notify builder 48 hours before each pour"),
    ("5.4", "Delay costs, standing time", None, "hr", None, None, 0.55,
     "Written direction required within 5 business days"),
]  # fmt: skip


class MockExtractionProvider:
    """Deterministic stand-in for the AI service.

    It never reads the document. The schedule is chosen from the filename, so
    the same upload always gives the same items. Confidence values are
    placeholders, not calibrated scores. Same schedules as the web prototype's
    mock (apps/web/lib/ai.ts), so demo and live modes behave alike.
    """

    def __init__(self, *, available: bool = True) -> None:
        self.available = available

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        if not self.available:
            raise AiUnavailableError()
        is_fitout = re.search(r"fitout|electrical", request.original_filename, re.IGNORECASE)
        schedule = _FITOUT_SCHEDULE if is_fitout else _FORMWORK_SCHEDULE
        return ExtractionResult(
            contract_id=request.contract_id,
            items=[
                ExtractedItem(
                    item_code=code,
                    description=description,
                    quantity=quantity,
                    unit=unit,
                    rate=rate,
                    amount=amount,
                    notice_requirement=notice,
                    confidence=confidence,
                    source_reference=f"Schedule of rates, item {code}",
                )
                for code, description, quantity, unit, rate, amount, confidence, notice in schedule
            ],
        )


class HttpExtractionProvider:
    """Calls the AI service: POST {AI_SERVICE_URL}/ai/v1/contracts/{contract_id}/extract."""

    def __init__(self, http: httpx2.Client, base_url: str) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        url = f"{self._base_url}/ai/v1/contracts/{request.contract_id}/extract"
        try:
            response = self._http.post(
                url, json=request.model_dump(mode="json"), timeout=AI_TIMEOUT_SECONDS
            )
        except httpx2.HTTPError as exc:
            logger.error("AI service unreachable: %s", exc)
            raise AiUnavailableError() from exc

        if not response.is_success:
            logger.error("AI service answered %s for contract extraction", response.status_code)
            raise AiUnavailableError()
        try:
            result = ExtractionResult.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            logger.error("AI service returned an unreadable extraction result: %s", exc)
            raise AiUnavailableError() from exc
        if result.contract_id != request.contract_id:
            logger.error("AI service answered for a different contract")
            raise AiUnavailableError()
        return result
