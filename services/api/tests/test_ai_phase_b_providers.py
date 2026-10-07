"""API-side providers for Phase B AI service capabilities."""

import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx2
import pytest
from pydantic import ValidationError

from app.ai.completeness import (
    CompletenessRequest,
    CompletenessResult,
    HttpCompletenessProvider,
    MockCompletenessProvider,
)
from app.ai.extraction import AiUnavailableError
from app.ai.matching import (
    EvidenceSignals,
    HttpMatchingProvider,
    MatchingContractItem,
    MatchingRequest,
    MatchingResult,
    MatchSuggestion,
    MockMatchingProvider,
)
from app.ai.variations import (
    HttpVariationProvider,
    MockVariationProvider,
    VariationDetectionRequest,
    VariationDetectionResult,
)
from app.api.deps import (
    get_completeness_provider,
    get_matching_provider,
    get_variation_provider,
)
from app.core.config import Settings

EVIDENCE_ID = UUID("eeeeeeee-0000-4000-8000-000000000001")
OTHER_EVIDENCE_ID = UUID("eeeeeeee-0000-4000-8000-000000000002")
ITEM_ID = UUID("11111111-0000-4000-8000-000000000001")

Handler = Callable[[httpx2.Request], httpx2.Response]


def recording(handler: Handler) -> tuple[httpx2.Client, list[httpx2.Request]]:
    requests: list[httpx2.Request] = []

    def record(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return handler(request)

    return httpx2.Client(transport=httpx2.MockTransport(record)), requests


def signals(text: str = "Level 3 formwork and concrete pour complete.") -> EvidenceSignals:
    return EvidenceSignals(
        objects=["formwork", "concrete"],
        activities=["concrete pour"],
        extracted_text=text,
        location="Level 3",
        date=datetime(2026, 9, 14, 1, 30, tzinfo=timezone.utc),
        other_signals={"source": "mobile_upload"},
    )


def item() -> MatchingContractItem:
    return MatchingContractItem(
        contract_item_id=ITEM_ID,
        item_code="2.1",
        description="Formwork, slab edges",
        quantity=180,
        unit="m²",
        amount=13500,
    )


def matching_request() -> MatchingRequest:
    return MatchingRequest(evidence_id=EVIDENCE_ID, signals=signals(), contract_items=[item()])


def suggestion(
    confidence: float = 0.91,
    assessment: str = "strong",
    missing_evidence: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "contract_item_id": str(ITEM_ID),
        "confidence": confidence,
        "assessment": assessment,
        "reason": "Evidence indicates formwork.",
        "missing_evidence": missing_evidence or [],
    }


def match_result(evidence_id: UUID = EVIDENCE_ID) -> dict[str, Any]:
    return {"evidence_id": str(evidence_id), "matches": [suggestion()]}


def completeness_request() -> CompletenessRequest:
    return CompletenessRequest(
        contract_item_id=ITEM_ID,
        matches=[MatchSuggestion.model_validate(suggestion())],
    )


def completeness_result(contract_item_id: UUID = ITEM_ID, status: str = "strong") -> dict[str, Any]:
    return {
        "contract_item_id": str(contract_item_id),
        "status": status,
        "confidence": 0.91,
        "reason": "Evidence support is strong.",
    }


def variation_request() -> VariationDetectionRequest:
    return VariationDetectionRequest(
        evidence_id=EVIDENCE_ID,
        signals=signals("Builder instructed extra penetrations not on the drawings."),
        matches=[],
    )


def variation_result(related: list[UUID] | None = None) -> dict[str, Any]:
    return {
        "potential_variation": True,
        "confidence": 0.72,
        "reason": "Evidence describes additional work.",
        "related_evidence_ids": [str(evidence_id) for evidence_id in (related or [EVIDENCE_ID])],
        "review_required": True,
    }


def test_http_matching_provider_success() -> None:
    http, requests = recording(lambda r: httpx2.Response(200, json=match_result()))
    result = HttpMatchingProvider(http, "http://ai.test/").match(matching_request())

    (request,) = requests
    assert request.method == "POST"
    assert str(request.url) == "http://ai.test/ai/v1/matches"
    body = json.loads(request.content)
    assert body["evidence_id"] == str(EVIDENCE_ID)
    assert body["contract_items"][0]["contract_item_id"] == str(ITEM_ID)
    assert isinstance(result, MatchingResult)
    assert result.matches[0].confidence == 0.91


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx2.Response(500, text="down"),
        lambda r: httpx2.Response(200, text="not json"),
        lambda r: httpx2.Response(200, json={"matches": []}),
        lambda r: httpx2.Response(
            200, json={**match_result(), "evidence_id": str(OTHER_EVIDENCE_ID)}
        ),
        lambda r: httpx2.Response(
            200, json={"evidence_id": str(EVIDENCE_ID), "matches": [suggestion(7)]}
        ),
        lambda r: httpx2.Response(
            200,
            json={"evidence_id": str(EVIDENCE_ID), "matches": [suggestion(0.8, "verified")]},
        ),
    ],
    ids=[
        "http-error",
        "malformed-json",
        "missing-field",
        "wrong-evidence",
        "bad-confidence",
        "bad-enum",
    ],
)
def test_http_matching_provider_rejects_unusable_answers(handler: Handler) -> None:
    http, _ = recording(handler)
    with pytest.raises(AiUnavailableError):
        HttpMatchingProvider(http, "http://ai.test").match(matching_request())


def test_http_matching_provider_connection_error() -> None:
    def refused(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    http, _ = recording(refused)
    with pytest.raises(AiUnavailableError):
        HttpMatchingProvider(http, "http://ai.test").match(matching_request())


def test_mock_matching_provider() -> None:
    result = MockMatchingProvider().match(matching_request())
    assert result.evidence_id == EVIDENCE_ID
    assert result.matches
    assert result.matches[0].assessment in {"strong", "partial", "weak"}
    with pytest.raises(AiUnavailableError):
        MockMatchingProvider(available=False).match(matching_request())


def test_matching_model_validation() -> None:
    with pytest.raises(ValidationError):
        MatchSuggestion.model_validate(suggestion(confidence=-0.1))
    with pytest.raises(ValidationError):
        MatchSuggestion.model_validate(suggestion(assessment="verified"))


def test_http_completeness_provider_success() -> None:
    http, requests = recording(lambda r: httpx2.Response(200, json=completeness_result()))
    result = HttpCompletenessProvider(http, "http://ai.test").assess(completeness_request())

    (request,) = requests
    assert str(request.url) == "http://ai.test/ai/v1/completeness"
    assert json.loads(request.content)["contract_item_id"] == str(ITEM_ID)
    assert isinstance(result, CompletenessResult)
    assert result.status == "strong"


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx2.Response(503, json={"error": {"code": "ai_unavailable"}}),
        lambda r: httpx2.Response(200, text="not json"),
        lambda r: httpx2.Response(200, json={"contract_item_id": str(ITEM_ID)}),
        lambda r: httpx2.Response(
            200, json=completeness_result(UUID("22222222-0000-4000-8000-000000000002"))
        ),
        lambda r: httpx2.Response(200, json=completeness_result(status="verified")),
        lambda r: httpx2.Response(200, json={**completeness_result(), "confidence": 9}),
    ],
    ids=[
        "http-error",
        "malformed-json",
        "missing-field",
        "wrong-item",
        "bad-status",
        "bad-confidence",
    ],
)
def test_http_completeness_provider_rejects_unusable_answers(handler: Handler) -> None:
    http, _ = recording(handler)
    with pytest.raises(AiUnavailableError):
        HttpCompletenessProvider(http, "http://ai.test").assess(completeness_request())


def test_mock_completeness_provider() -> None:
    assert MockCompletenessProvider().assess(completeness_request()).status == "strong"
    missing = MockCompletenessProvider().assess(
        CompletenessRequest(contract_item_id=ITEM_ID, matches=[])
    )
    assert missing.status == "missing"
    with pytest.raises(AiUnavailableError):
        MockCompletenessProvider(available=False).assess(completeness_request())


def test_http_variation_provider_success() -> None:
    http, requests = recording(lambda r: httpx2.Response(200, json=variation_result()))
    result = HttpVariationProvider(http, "http://ai.test").detect(variation_request())

    (request,) = requests
    assert str(request.url) == "http://ai.test/ai/v1/variations/detect"
    assert json.loads(request.content)["evidence_id"] == str(EVIDENCE_ID)
    assert isinstance(result, VariationDetectionResult)
    assert result.potential_variation is True


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx2.Response(500, text="down"),
        lambda r: httpx2.Response(200, text="not json"),
        lambda r: httpx2.Response(200, json={"potential_variation": True}),
        lambda r: httpx2.Response(200, json=variation_result([OTHER_EVIDENCE_ID])),
        lambda r: httpx2.Response(200, json={**variation_result(), "confidence": 4}),
        lambda r: httpx2.Response(200, json={**variation_result(), "review_required": "yes"}),
    ],
    ids=[
        "http-error",
        "malformed-json",
        "missing-field",
        "wrong-evidence",
        "bad-confidence",
        "bad-type",
    ],
)
def test_http_variation_provider_rejects_unusable_answers(handler: Handler) -> None:
    http, _ = recording(handler)
    with pytest.raises(AiUnavailableError):
        HttpVariationProvider(http, "http://ai.test").detect(variation_request())


def test_mock_variation_provider() -> None:
    result = MockVariationProvider().detect(variation_request())
    assert result.potential_variation is True
    assert result.related_evidence_ids == [EVIDENCE_ID]
    with pytest.raises(AiUnavailableError):
        MockVariationProvider(available=False).detect(variation_request())


def test_provider_selection() -> None:
    http = httpx2.Client(transport=httpx2.MockTransport(lambda r: httpx2.Response(200)))
    settings: Any = Settings(_env_file=None)
    assert isinstance(get_matching_provider(settings, http), MockMatchingProvider)
    assert isinstance(get_completeness_provider(settings, http), MockCompletenessProvider)
    assert isinstance(get_variation_provider(settings, http), MockVariationProvider)

    http_settings: Any = Settings(
        _env_file=None,
        ai_matching_provider="http",
        ai_completeness_provider="http",
        ai_variation_provider="http",
        ai_service_url="http://ai.test",
    )
    assert isinstance(get_matching_provider(http_settings, http), HttpMatchingProvider)
    assert isinstance(get_completeness_provider(http_settings, http), HttpCompletenessProvider)
    assert isinstance(get_variation_provider(http_settings, http), HttpVariationProvider)
