from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.providers.base import EmbeddingProvider, LLMProvider, VisionProvider
from app.providers.mock import MockEmbeddingProvider, MockLLMProvider, MockVisionProvider
from app.schemas.completeness import CompletenessResult
from app.schemas.evidence import EvidenceSignals, EvidenceUnderstandingRequest
from app.schemas.extraction import ExtractedContractItem, ExtractionRequest
from app.schemas.matching import MatchingContractItem, MatchingResult, MatchSuggestion
from app.schemas.variations import VariationDetectionResult
from app.services.extraction import MockExtractionProvider

API = "/ai/v1"
CONTRACT_ID = UUID("cccccccc-0000-4000-8000-000000000001")
EVIDENCE_ID = UUID("eeeeeeee-0000-4000-8000-000000000001")
PROJECT_ID = UUID("aaaaaaaa-0000-4000-8000-000000000001")
ITEM_ID = UUID("11111111-0000-4000-8000-000000000001")


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def extraction_request(filename: str = "Subcontract_HumeSt_Formwork.pdf") -> dict:
    return {
        "contract_id": str(CONTRACT_ID),
        "original_filename": filename,
        "mime_type": "application/pdf",
        "document_url": "https://storage.test/contracts/p/c/original.pdf?token=signed",
    }


def evidence_request(description: str = "Level 3 slab pour completed east side.") -> dict:
    return {
        "evidence_id": str(EVIDENCE_ID),
        "project_id": str(PROJECT_ID),
        "evidence_type": "photo",
        "title": "Level 3 slab pour",
        "description": description,
        "captured_at": "2026-09-14T01:30:00Z",
        "metadata": {"location": "Level 3 east", "source": "mobile_upload", "tags": ["slab"]},
        "original_filename": "IMG_2041.jpg",
        "mime_type": "image/jpeg",
        "document_url": "https://storage.test/evidence/p/e/original.jpg?token=signed",
    }


def signals() -> dict:
    return {
        "objects": ["formwork", "concrete"],
        "activities": ["concrete pour"],
        "extracted_text": "Level 3 formwork and concrete pour complete.",
        "location": "Level 3",
        "date": "2026-09-14T01:30:00Z",
        "other_signals": {"source": "mobile_upload"},
    }


def match_suggestion(confidence: float = 0.91, assessment: str = "strong") -> dict:
    return {
        "contract_item_id": str(ITEM_ID),
        "confidence": confidence,
        "assessment": assessment,
        "reason": "Evidence overlaps with contract line.",
        "missing_evidence": [],
    }


def test_health(client: TestClient) -> None:
    response = client.get(f"{API}/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "subpay-ai",
        "version": "0.1.0",
        "environment": "development",
        "provider_mode": "mock",
    }


def test_extraction_schema_validation() -> None:
    request = ExtractionRequest.model_validate(extraction_request())
    assert request.contract_id == CONTRACT_ID

    with pytest.raises(ValidationError):
        ExtractedContractItem(item_code="", description="x", confidence=0.5)
    with pytest.raises(ValidationError):
        ExtractedContractItem(item_code="1", description="x", confidence=1.5)


def test_extraction_mock_provider_is_deterministic() -> None:
    provider = MockExtractionProvider()
    request = ExtractionRequest.model_validate(extraction_request())
    first = provider.extract(request)
    second = provider.extract(request)
    assert first == second
    assert [item.item_code for item in first.items] == ["1.1", "2.1", "2.2", "3.1", "5.4"]


def test_nullable_missing_extraction_fields(client: TestClient) -> None:
    response = client.post(f"{API}/contracts/{CONTRACT_ID}/extract", json=extraction_request())
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    standing_time = next(item for item in items if item["item_code"] == "5.4")
    assert standing_time["quantity"] is None
    assert standing_time["rate"] is None
    assert standing_time["amount"] is None


def test_evidence_signals_schema() -> None:
    request = EvidenceUnderstandingRequest.model_validate(evidence_request())
    evidence_signals = EvidenceSignals(
        objects=["formwork"],
        activities=["completed work"],
        extracted_text=request.description,
        location="Level 3",
        date=datetime(2026, 9, 14, 1, 30, tzinfo=timezone.utc),
        other_signals={"evidence_type": request.evidence_type},
    )
    assert evidence_signals.location == "Level 3"
    assert evidence_signals.other_signals["evidence_type"] == "photo"


def test_evidence_understanding_endpoint(client: TestClient) -> None:
    response = client.post(f"{API}/evidence/{EVIDENCE_ID}/understand", json=evidence_request())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["evidence_id"] == str(EVIDENCE_ID)
    assert "concrete pour" in body["signals"]["activities"]
    assert body["signals"]["location"] == "Level 3 east"


def test_matching_response_validation(client: TestClient) -> None:
    response = client.post(
        f"{API}/matches",
        json={
            "evidence_id": str(EVIDENCE_ID),
            "signals": signals(),
            "contract_items": [
                {
                    "contract_item_id": str(ITEM_ID),
                    "item_code": "2.1",
                    "description": "Formwork, slab edges",
                    "quantity": 180,
                    "unit": "m2",
                    "amount": 13500,
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    result = MatchingResult.model_validate(response.json())
    assert result.evidence_id == EVIDENCE_ID
    assert result.matches
    assert result.matches[0].assessment in {"strong", "partial", "weak"}


def test_completeness_response_validation(client: TestClient) -> None:
    response = client.post(
        f"{API}/completeness",
        json={"contract_item_id": str(ITEM_ID), "matches": [match_suggestion()]},
    )
    assert response.status_code == 200, response.text
    result = CompletenessResult.model_validate(response.json())
    assert result.status == "strong"
    assert "Evidence support" in result.reason

    missing = client.post(
        f"{API}/completeness",
        json={"contract_item_id": str(ITEM_ID), "matches": []},
    )
    assert missing.status_code == 200
    assert missing.json()["status"] == "missing"


def test_variation_response_validation(client: TestClient) -> None:
    response = client.post(
        f"{API}/variations/detect",
        json={
            "evidence_id": str(EVIDENCE_ID),
            "signals": {
                **signals(),
                "extracted_text": "Builder instructed extra penetrations not on the drawings.",
            },
            "matches": [],
        },
    )
    assert response.status_code == 200, response.text
    result = VariationDetectionResult.model_validate(response.json())
    assert result.potential_variation is True
    assert result.review_required is True
    assert result.related_evidence_ids == [EVIDENCE_ID]


def test_malformed_request_handling(client: TestClient) -> None:
    response = client.post(
        f"{API}/matches",
        json={
            "evidence_id": str(EVIDENCE_ID),
            "signals": signals(),
            "contract_items": [
                {
                    "contract_item_id": str(ITEM_ID),
                    "item_code": "2.1",
                    "description": "Formwork, slab edges",
                    "quantity": -1,
                }
            ],
        },
    )
    assert response.status_code == 422

    with pytest.raises(ValidationError):
        MatchSuggestion.model_validate({**match_suggestion(), "assessment": "verified"})


def test_provider_abstraction() -> None:
    class NeedsProviders(Protocol):
        llm: LLMProvider
        embeddings: EmbeddingProvider
        vision: VisionProvider

    class Bundle:
        llm = MockLLMProvider()
        embeddings = MockEmbeddingProvider()
        vision = MockVisionProvider()

    bundle: NeedsProviders = Bundle()
    assert bundle.llm.complete("Hello") == bundle.llm.complete("hello")
    assert bundle.embeddings.embed("concrete") == bundle.embeddings.embed("CONCRETE")
    assert "formwork" in bundle.vision.describe(document_url=None, text_hint="Formwork photo")


def test_mock_provider_behaviour() -> None:
    embedding = MockEmbeddingProvider().embed("Level 3 slab pour")
    assert len(embedding) == 8
    assert embedding == MockEmbeddingProvider().embed("level 3 slab pour")

    fitout = MockExtractionProvider().extract(
        ExtractionRequest.model_validate(extraction_request("Riverside_Fitout.pdf"))
    )
    assert [item.item_code for item in fitout.items] == ["4.2", "4.3", "4.5", "6.1"]


def test_matching_accepts_nullable_item_fields() -> None:
    item = MatchingContractItem(
        contract_item_id=ITEM_ID,
        item_code="5.4",
        description="Delay costs, standing time",
        quantity=None,
        unit="hr",
        amount=None,
    )
    assert item.quantity is None and item.amount is None
