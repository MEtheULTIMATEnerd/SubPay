import base64
import json

import httpx2
import pytest

from app.local_vision import OpenAIServiceVision, get_local_vision
from tests.test_integrated import HEADERS, TOKEN, client_for
from tests.test_local_evidence import image_bytes

GROUPS = {
    "objects_certain": ["electrical distribution board", "wiring"],
    "objects_possible": [],
    "activities_certain": [],
    "activities_possible": [],
}


@pytest.mark.parametrize(
    "failure", [None, "empty", 401, 429, 502, "timeout", "malformed", "wrong-model"]
)
def test_http_adapter_persistence(tmp_path, failure):
    c = client_for(tmp_path)
    project = c.post("/projects", headers=HEADERS, json={"name": "Site"}).json()["id"]
    data = image_bytes()
    base = f"/projects/{project}/evidence"
    evidence = c.post(base, headers=HEADERS, files={"file": ("site.png", data, "image/png")}).json()
    requests = []

    def handle(request):
        requests.append(request)
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        url = json.loads(request.content)["document_url"]
        assert url.startswith("data:image/png;base64,")
        assert base64.b64decode(url.split(",")[1]) == data
        if failure == "timeout":
            raise httpx2.ReadTimeout("timeout", request=request)
        if isinstance(failure, int):
            return httpx2.Response(failure, json={"detail": "sensitive upstream error"})
        if failure == "malformed":
            return httpx2.Response(
                200,
                json={"provider": "openai", "model": "gpt-4o-mini", "observations": {"bad": True}},
            )
        return httpx2.Response(
            200,
            json={
                "provider": "openai",
                "model": "wrong" if failure == "wrong-model" else "gpt-4o-mini",
                "observations": {k: [] for k in GROUPS} if failure == "empty" else GROUPS,
            },
        )

    c.app.dependency_overrides[get_local_vision] = lambda: OpenAIServiceVision(
        TOKEN, "gpt-4o-mini", httpx2.MockTransport(handle)
    )
    response = c.post(base + "/" + evidence["id"] + "/analyse", headers=HEADERS)
    assert len(requests) == 1
    assert response.status_code == (200 if failure in (None, "empty") else 502)
    rows = (
        client_for(tmp_path)
        .get(base + "/" + evidence["id"] + "/observations", headers=HEADERS)
        .json()
    )
    assert rows[0]["provider"] == "openai"
    assert rows[0]["model"] == "gpt-4o-mini"
    assert rows[0]["processed_at"]
    if failure in (None, "empty"):
        assert rows[0]["structured_data"]["mock"] is False
        assert rows[0]["structured_data"]["observations"] == (
            {k: [] for k in GROUPS} if failure == "empty" else GROUPS
        )
    else:
        assert rows[0]["status"] == "failed"
        assert rows[0]["structured_data"] is None
        assert "sensitive" not in str(rows)
