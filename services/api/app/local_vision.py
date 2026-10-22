"""Local vision boundary: mock or authenticated loopback AI-service bridge."""

import base64
from typing import Annotated, Protocol

import httpx2
from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.ai.evidence import EvidenceUnderstandingResult
from app.ai.matching import EvidenceSignals

Label = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=100)]


class Observations(BaseModel):
    """Same four certainty/activity groups used by services/ai VisionProvider."""

    model_config = ConfigDict(extra="forbid")
    objects_certain: list[Label] = Field(max_length=100)
    objects_possible: list[Label] = Field(max_length=100)
    activities_certain: list[Label] = Field(max_length=100)
    activities_possible: list[Label] = Field(max_length=100)


class VisionProvider(Protocol):
    def describe(
        self, *, document_url: str | None, text_hint: str = ""
    ) -> dict[str, list[str]]: ...


class LocalMockVision:
    provider_name = "mock"
    model = "local-mock-v1"

    def describe(self, *, document_url: str | None, text_hint: str = "") -> dict[str, list[str]]:
        return {
            "objects_certain": [],
            "objects_possible": ["MOCK: source image supplied"],
            "activities_certain": [],
            "activities_possible": [],
        }


class OpenAIServiceVision:
    provider_name = "openai"

    def __init__(self, token, model, transport=None):
        self.token = token
        self.model = model
        self.transport = transport

    def describe(self, *, document_url, text_hint=""):
        with httpx2.Client(timeout=40, transport=self.transport, trust_env=False) as client:
            response = client.post(
                "http://127.0.0.1:8001/ai/v1/local/vision",
                headers={"Authorization": f"Bearer {self.token}"},
                json={"document_url": document_url},
            )
        if response.status_code != 200:
            raise ValueError("Vision service failed")
        body = response.json()
        if body.get("provider") != "openai" or body.get("model") != self.model:
            raise ValueError("Vision provenance mismatch")
        return Observations.model_validate(body["observations"]).model_dump()


def get_local_vision(request: Request):
    settings = request.app.state.local_settings
    if settings.vision_provider == "mock":
        return LocalMockVision()
    return OpenAIServiceVision(settings.access_token.get_secret_value(), settings.vision_model)


def analyse(provider: VisionProvider, evidence_id, data: bytes, content_type: str):
    mock = getattr(provider, "provider_name", "mock") == "mock"
    url = f"data:{content_type};base64,{base64.b64encode(data).decode('ascii')}"
    observations = Observations.model_validate(provider.describe(document_url=url, text_hint=""))
    result = EvidenceUnderstandingResult(
        evidence_id=evidence_id,
        confidence=0.0,
        signals=EvidenceSignals(
            objects=observations.objects_certain + observations.objects_possible,
            activities=observations.activities_certain + observations.activities_possible,
            other_signals={"mock": mock, "not_real_vision": mock, "confidence_calibrated": False},
        ),
    )
    return {
        "mock": mock,
        "observations": observations.model_dump(),
        "understanding": result.model_dump(mode="json"),
    }
