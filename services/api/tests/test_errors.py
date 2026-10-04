"""Every failure uses the same error shape (docs/api-contracts.md)."""

from fastapi.testclient import TestClient


def test_api_error_helper_produces_the_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/_test/missing")
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Project not found"}}


def test_unknown_route_uses_the_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_wrong_method_uses_the_error_envelope(client: TestClient) -> None:
    response = client.delete("/api/v1/health")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


def test_validation_errors_list_the_fields(client: TestClient) -> None:
    response = client.post("/api/v1/_test/echo", json={"name": "", "quantity": "lots"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["message"] == "Request validation failed"
    assert {d["field"] for d in error["details"]} == {"name", "quantity"}
    assert all(d["message"] for d in error["details"])


def test_unexpected_errors_do_not_leak_internals(client: TestClient) -> None:
    response = client.get("/api/v1/_test/boom")
    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "Something went wrong. Please try again.",
        }
    }
    assert "secret internal detail" not in response.text
