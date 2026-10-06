"""The AI boundary: the mock provider and the HTTP provider behind one interface."""

import json
from collections.abc import Callable
from uuid import UUID

import httpx2
import pytest

from app.ai.extraction import (
    AiUnavailableError,
    ExtractionRequest,
    ExtractionResult,
    HttpExtractionProvider,
    MockExtractionProvider,
)
from app.api.deps import get_extraction_provider
from app.core.config import Settings

CONTRACT_ID = UUID("cccccccc-0000-4000-8000-000000000001")
REQUEST = ExtractionRequest(
    contract_id=CONTRACT_ID,
    original_filename="Subcontract_HumeSt_Formwork.pdf",
    mime_type="application/pdf",
    document_url="https://storage.test/contracts/p/c/original.pdf?token=signed",
)
AI_ANSWER = {
    "contract_id": str(CONTRACT_ID),
    "items": [
        {
            "item_code": "4.2",
            "description": "Electrical conduit installation",
            "quantity": 120,
            "unit": "m",
            "rate": 45,
            "amount": 5400,
            "conditions": None,
            "notice_requirement": None,
            "due_date": None,
            "confidence": 0.91,
        },
        {"item_code": "9.1", "description": "Provisional sum", "confidence": 0.4},
    ],
}

Handler = Callable[[httpx2.Request], httpx2.Response]


def http_provider(handler: Handler) -> tuple[HttpExtractionProvider, list[httpx2.Request]]:
    requests: list[httpx2.Request] = []

    def record(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return handler(request)

    client = httpx2.Client(transport=httpx2.MockTransport(record))
    return HttpExtractionProvider(client, "http://ai.test/"), requests


# ---- mock provider ------------------------------------------------------------


def test_mock_extraction_is_deterministic() -> None:
    provider = MockExtractionProvider()
    first, second = provider.extract(REQUEST), provider.extract(REQUEST)
    assert first == second
    assert first.contract_id == CONTRACT_ID
    assert [i.item_code for i in first.items] == ["1.1", "2.1", "2.2", "3.1", "5.4"]


def test_mock_extraction_picks_a_schedule_from_the_filename() -> None:
    fitout = MockExtractionProvider().extract(
        REQUEST.model_copy(update={"original_filename": "Riverside_Commercial_FITOUT.docx"})
    )
    assert [i.item_code for i in fitout.items] == ["4.2", "4.3", "4.5", "6.1"]


def test_mock_results_look_like_real_ones() -> None:
    result = MockExtractionProvider().extract(REQUEST)
    assert all(0 <= item.confidence <= 1 for item in result.items)
    assert any(item.quantity is None for item in result.items)  # not every field is always present
    assert any(item.notice_requirement for item in result.items)
    assert all(item.source_reference for item in result.items)


def test_mock_can_simulate_an_outage() -> None:
    with pytest.raises(AiUnavailableError) as caught:
        MockExtractionProvider(available=False).extract(REQUEST)
    assert "AI analysis unavailable" in str(caught.value)


# ---- http provider ------------------------------------------------------------


def test_http_provider_calls_the_agreed_endpoint_with_the_agreed_body() -> None:
    provider, requests = http_provider(lambda r: httpx2.Response(200, json=AI_ANSWER))
    result = provider.extract(REQUEST)

    (request,) = requests
    assert request.method == "POST"
    assert str(request.url) == f"http://ai.test/ai/v1/contracts/{CONTRACT_ID}/extract"
    assert json.loads(request.content) == {
        "contract_id": str(CONTRACT_ID),
        "original_filename": "Subcontract_HumeSt_Formwork.pdf",
        "mime_type": "application/pdf",
        "document_url": "https://storage.test/contracts/p/c/original.pdf?token=signed",
    }
    assert isinstance(result, ExtractionResult)
    assert result.items[0].amount == 5400
    # only code, description and confidence are guaranteed; the rest default to null
    assert result.items[1].quantity is None and result.items[1].source_reference is None


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx2.Response(503, json={"error": {"code": "ai_unavailable"}}),
        lambda r: httpx2.Response(500, text="Traceback ..."),
        lambda r: httpx2.Response(200, text="not json"),
        lambda r: httpx2.Response(200, json={"items": []}),  # no contract_id
        lambda r: httpx2.Response(
            200,
            json={**AI_ANSWER, "items": [{"item_code": "1", "description": "x", "confidence": 7}]},
        ),
        lambda r: httpx2.Response(
            200, json={**AI_ANSWER, "contract_id": "dddddddd-0000-4000-8000-000000000009"}
        ),
    ],
    ids=["503", "500", "not-json", "missing-field", "confidence-out-of-range", "wrong-contract"],
)
def test_any_unusable_answer_is_an_ai_outage(handler: Handler) -> None:
    provider, _ = http_provider(handler)
    with pytest.raises(AiUnavailableError):
        provider.extract(REQUEST)


def test_an_unreachable_ai_service_is_an_ai_outage() -> None:
    def unreachable(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    provider, _ = http_provider(unreachable)
    with pytest.raises(AiUnavailableError):
        provider.extract(REQUEST)


# ---- choosing the provider ----------------------------------------------------


def test_the_provider_is_chosen_by_configuration() -> None:
    http = httpx2.Client(transport=httpx2.MockTransport(lambda r: httpx2.Response(200)))
    mock = get_extraction_provider(Settings(_env_file=None), http)
    real = get_extraction_provider(
        Settings(_env_file=None, ai_extraction_provider="http", ai_service_url="http://ai.test"),
        http,
    )
    assert isinstance(mock, MockExtractionProvider)  # the default needs no AI service
    assert isinstance(real, HttpExtractionProvider)
