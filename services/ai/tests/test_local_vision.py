import base64
import json

import httpx2
import pytest
from fastapi.testclient import TestClient

from app import local_vision
from app.core.config import Settings, get_settings
from app.main import create_app
from app.providers.openai import OpenAIVisionProvider

TOKEN = "test-local-token-only-12345678901234567890"


@pytest.mark.parametrize(
    "failure", [None, 401, 429, "timeout", "invalid-json", "wrong-shape", "invalid-label"]
)
def test_bridge_reuses_openai_payload_and_strict_parser(monkeypatch, failure):
    requests = []
    image = "data:image/png;base64," + base64.b64encode(b"test-bytes-validated-by-api").decode()

    def handle(request):
        requests.append(request)
        body = json.loads(request.content)
        assert body["model"] == "gpt-4o-mini"
        assert body["max_tokens"] == 500
        assert body["messages"][0]["role"] == "system"
        prompt = body["messages"][0]["content"]
        assert "electrical distribution boards" in prompt
        assert "construction objects, materials" in prompt
        assert "objects_certain" in prompt and "activities_possible" in prompt
        assert body["messages"][1]["content"][1]["image_url"] == {"url": image, "detail": "low"}
        if failure == "timeout":
            raise httpx2.ReadTimeout("timeout", request=request)
        if isinstance(failure, int):
            return httpx2.Response(failure)
        content = {"invalid-json": "not JSON", "wrong-shape": "{}", "invalid-label": "[123]"}.get(
            failure,
            '["certain: formwork", '
            '{"type":"activity","certainty":"possible","label":"installation"}]',
        )
        return httpx2.Response(200, json={"choices": [{"message": {"content": content}}]})

    def factory(**kwargs):
        provider = OpenAIVisionProvider(**kwargs)
        provider._client.close()
        provider._client = httpx2.Client(transport=httpx2.MockTransport(handle))
        return provider

    monkeypatch.setattr(local_vision, "OpenAIVisionProvider", factory)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        vision_provider="openai",
        openai_api_key="test-only",
        local_vision_enabled=True,
        local_access_token=TOKEN,
    )
    c = TestClient(app, client=("127.0.0.1", 1234))
    response = c.post(
        "/ai/v1/local/vision",
        json={"document_url": image},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert len(requests) == 1
    assert response.status_code == (200 if failure is None else 502)
    if failure is None:
        assert response.json()["observations"]["objects_certain"] == ["formwork"]
        assert response.json()["observations"]["activities_possible"] == ["installation"]
        assert response.json()["provider"] == "openai"
    else:
        assert "observations" not in response.json()


def test_disabled_bridge_never_calls_provider(monkeypatch):
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, local_vision_enabled=False
    )

    def forbidden(**kwargs):
        pytest.fail("Provider must not be invoked")

    monkeypatch.setattr(local_vision, "OpenAIVisionProvider", forbidden)
    assert (
        TestClient(app).post("/ai/v1/local/vision", json={"document_url": "anything"}).status_code
        == 404
    )


@pytest.mark.parametrize(
    "headers,client_address",
    [
        ({}, "127.0.0.1"),
        ({"Authorization": "Bearer wrong"}, "127.0.0.1"),
        ({"Authorization": f"Bearer {TOKEN}"}, "192.0.2.1"),
    ],
)
def test_bridge_requires_local_token(monkeypatch, headers, client_address):
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        local_vision_enabled=True,
        local_access_token=TOKEN,
        vision_provider="openai",
        openai_api_key="test-only",
    )

    def forbidden(**kwargs):
        pytest.fail("Unauthorised request must not instantiate provider")

    monkeypatch.setattr(local_vision, "OpenAIVisionProvider", forbidden)
    c = TestClient(app, client=(client_address, 1234))
    assert (
        c.post(
            "/ai/v1/local/vision", json={"document_url": "anything"}, headers=headers
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "raw,expected",
    [
        (
            "[]",
            {
                "objects_certain": [],
                "objects_possible": [],
                "activities_certain": [],
                "activities_possible": [],
            },
        ),
        (
            '[{"type":"object","certainty":"certain","label":"electrical distribution board"},'
            '{"type":"object","certainty":"possible","label":"meter"},'
            '{"type":"activity","certainty":"certain","label":"worker handling cable"},'
            '{"type":"activity","certainty":"possible","label":"cable routing"}]',
            {
                "objects_certain": ["electrical distribution board"],
                "objects_possible": ["meter"],
                "activities_certain": ["worker handling cable"],
                "activities_possible": ["cable routing"],
            },
        ),
        (
            '["certain: wiring", "possible: conduit"]',
            {
                "objects_certain": ["wiring"],
                "objects_possible": ["conduit"],
                "activities_certain": [],
                "activities_possible": [],
            },
        ),
    ],
)
def test_strict_observations_preserved_by_mocked_http(raw, expected):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx2.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {"content": raw}}]}
        )

    with OpenAIVisionProvider(
        api_key="test-only",
        base_url="https://offline.test",
        model="gpt-4o-mini",
        strict_response=True,
        image_detail="low",
    ) as p:
        p._client.close()
        p._client = httpx2.Client(transport=httpx2.MockTransport(handle))
        assert p.describe(document_url="data:image/jpeg;base64,dGVzdA==") == expected
        assert len(requests) == 1


@pytest.mark.parametrize(
    "content,finish,refusal",
    [
        ("[]", "length", None),
        ("[]", "content_filter", None),
        ("[]", "stop", "refused"),
        ("{}", "stop", None),
        ("not json", "stop", None),
        ("[null]", "stop", None),
        ('["unsupported format"]', "stop", None),
        ("", "stop", None),
    ],
)
def test_strict_invalid_or_truncated_does_not_become_empty(content, finish, refusal):
    from app.providers.openai import OpenAIVisionError

    def handle(request):
        return httpx2.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": finish, "message": {"content": content, "refusal": refusal}}
                ]
            },
        )

    with OpenAIVisionProvider(
        api_key="test-only",
        base_url="https://offline.test",
        model="gpt-4o-mini",
        strict_response=True,
    ) as p:
        p._client.close()
        p._client = httpx2.Client(transport=httpx2.MockTransport(handle))
        with pytest.raises(OpenAIVisionError):
            p.describe(document_url="data:image/png;base64,dGVzdA==")
