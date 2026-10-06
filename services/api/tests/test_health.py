from fastapi.testclient import TestClient


def test_health_needs_no_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "subpay-api",
        "version": "0.1.0",
        "environment": "test",
    }


def test_openapi_schema_is_served_under_the_versioned_prefix(client: TestClient) -> None:
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "SubPay API"
    assert "/api/v1/health" in schema["paths"]


def test_interactive_docs_are_served(client: TestClient) -> None:
    assert client.get("/api/v1/docs").status_code == 200


def test_nothing_is_served_outside_the_versioned_prefix(client: TestClient) -> None:
    assert client.get("/health").status_code == 404
