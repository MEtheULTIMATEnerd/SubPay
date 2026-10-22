from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.integrated import LocalSettings, connect, create_local_app
from app.main import create_app

TOKEN = "test-only-local-token-not-a-real-secret-12345"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def client_for(path, **kwargs):
    settings = LocalSettings(enabled=True, access_token=SecretStr(TOKEN), data_dir=path)
    return TestClient(
        create_local_app(settings), client=kwargs.pop("client", ("127.0.0.1", 1234)), **kwargs
    )


def test_creation_listing_retrieval_and_reconnection(tmp_path):
    client = client_for(tmp_path)
    response = client.post(
        "/projects", json={"name": " Site A ", "description": "Real project"}, headers=HEADERS
    )
    assert response.status_code == 201
    project = response.json()
    assert project["name"] == "Site A"
    assert project["created_at"] == project["updated_at"]
    # New app and new SQLite connections must see the same durable record.
    fresh = client_for(tmp_path)
    assert fresh.get("/projects", headers=HEADERS).json() == [project]
    assert fresh.get(f"/projects/{project['id']}", headers=HEADERS).json() == project
    with connect(tmp_path / "projects.sqlite3") as db:
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": " "},
        {"name": "x" * 201},
        {"name": "ok", "description": "x" * 5001},
        {"name": "ok", "extra": True},
        {"name": "bad\x00"},
    ],
)
def test_invalid_input(tmp_path, body):
    assert client_for(tmp_path).post("/projects", json=body, headers=HEADERS).status_code == 422


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": f"Basic {TOKEN}"}]
)
def test_unauthorised(tmp_path, headers):
    assert client_for(tmp_path).get("/projects", headers=headers).status_code == 401
    assert not (tmp_path / "projects.sqlite3").exists()


def test_boundaries_and_missing_records(tmp_path):
    c = client_for(tmp_path)
    assert c.get("/projects", headers={**HEADERS, "Origin": "https://evil.test"}).status_code == 403
    assert (
        c.get("/projects", headers={**HEADERS, "Origin": "http://localhost:3101"}).status_code
        == 200
    )
    assert (
        client_for(tmp_path, client=("192.0.2.1", 1234))
        .get("/projects", headers=HEADERS)
        .status_code
        == 403
    )
    assert c.get(f"/projects/{uuid4()}", headers=HEADERS).status_code == 404
    assert c.get("/projects/not-a-uuid", headers=HEADERS).status_code == 422


def test_parameterised_sql(tmp_path):
    c = client_for(tmp_path)
    name = "Robert'); DROP TABLE projects;--"
    assert c.post("/projects", json={"name": name}, headers=HEADERS).status_code == 201
    assert c.get("/projects", headers=HEADERS).json()[0]["name"] == name


def test_disabled_and_health(monkeypatch):
    monkeypatch.delenv("SUBPAY_LOCAL_ENABLED", raising=False)
    assert LocalSettings().enabled is False
    app = create_app(Settings(_env_file=None))
    c = TestClient(app)
    assert c.get("/api/v1/integrated/projects").status_code == 404
    assert c.get("/api/v1/health").status_code == 200


def test_mounted_routes_and_cors(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBPAY_LOCAL_ENABLED", "true")
    monkeypatch.setenv("SUBPAY_LOCAL_ACCESS_TOKEN", TOKEN)
    monkeypatch.setenv("SUBPAY_LOCAL_DATA_DIR", str(tmp_path))
    c = TestClient(create_app(Settings(_env_file=None)), client=("127.0.0.1", 1234))
    url = "/api/v1/integrated/projects"
    assert c.post(url, headers=HEADERS, json={"name": "Mounted"}).status_code == 201
    response = c.options(
        url,
        headers={
            "Origin": "http://localhost:3101",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization,Content-Type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3101"
    assert (
        c.options(
            url, headers={"Origin": "https://evil.test", "Access-Control-Request-Method": "POST"}
        ).status_code
        == 400
    )
    assert c.get("/api/v1/health").status_code == 200


def test_missing_token_fails_closed():
    with pytest.raises(ValueError, match="ACCESS_TOKEN"):
        create_local_app(LocalSettings(enabled=True, access_token=SecretStr("")))
