import base64
from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image

from app import local_evidence
from app.integrated import LocalSettings, create_local_app
from app.local_vision import get_local_vision
from tests.test_integrated import HEADERS, TOKEN, client_for


def image_bytes(kind="PNG"):
    out = BytesIO()
    Image.new("RGB", (12, 10), "green").save(out, format=kind)
    return out.getvalue()


@pytest.fixture
def workflow(tmp_path):
    c = client_for(tmp_path)
    pid = c.post("/projects", json={"name": "Site"}, headers=HEADERS).json()["id"]
    return c, f"/projects/{pid}/evidence", tmp_path


def upload(c, base, data=None, mime="image/png", name="../../site.png", headers=HEADERS):
    return c.post(
        base,
        files={"file": (name, data if data is not None else image_bytes(), mime)},
        headers=headers,
    )


@pytest.mark.parametrize(
    "kind,mime,extension",
    [("JPEG", "image/jpeg", ".jpg"), ("PNG", "image/png", ".png"), ("WEBP", "image/webp", ".webp")],
)
def test_valid_images_private_and_unchanged(workflow, kind, mime, extension):
    c, base, directory = workflow
    data = image_bytes(kind)
    r = upload(c, base, data, mime, "misleading.exe")
    assert r.status_code == 201
    record = r.json()
    path = directory / record["stored_filename"]
    assert path.read_bytes() == data
    assert path.suffix == extension
    assert path.stem == record["id"]
    assert record["content_type"] == mime
    assert record["size"] == len(data)
    assert record["processing_status"] == "uploaded"
    assert c.get(base, headers=HEADERS).json() == [record]
    assert c.get(base + "/" + record["id"], headers=HEADERS).json() == record
    assert c.get("/uploads/" + path.name, headers=HEADERS).status_code == 404


@pytest.mark.parametrize(
    "data,mime",
    [
        (b"bad", "image/png"),
        (b"\x89PNG\r\n\x1a\ntruncated", "image/png"),
        (image_bytes("GIF"), "image/gif"),
        (image_bytes(), "image/jpeg"),
    ],
)
def test_invalid_images_leave_no_record(workflow, data, mime):
    c, base, directory = workflow
    assert upload(c, base, data, mime).status_code in (415, 422)
    assert c.get(base, headers=HEADERS).json() == []
    assert not list(directory.rglob("*.png"))


def test_limits(workflow, monkeypatch):
    c, base, _ = workflow
    monkeypatch.setattr(local_evidence, "MAX_IMAGE", 10)
    assert upload(c, base).status_code == 413
    monkeypatch.setattr(local_evidence, "MAX_IMAGE", 10000)
    monkeypatch.setattr(local_evidence, "MAX_PIXELS", 10)
    assert upload(c, base).status_code == 422


def test_project_access_and_auth(workflow):
    c, base, _ = workflow
    record = upload(c, base).json()
    other = c.post("/projects", json={"name": "Other"}, headers=HEADERS).json()["id"]
    wrong = f"/projects/{other}/evidence/{record['id']}"
    for suffix in ["", "/observations"]:
        assert c.get(wrong + suffix, headers=HEADERS).status_code == 404
    assert c.post(wrong + "/analyse", headers=HEADERS).status_code == 404
    assert upload(c, f"/projects/{uuid4()}/evidence").status_code == 404
    for headers in [{}, {"Authorization": "Bearer invalid"}]:
        assert upload(c, base, headers=headers).status_code == 401
        assert c.get(base, headers=headers).status_code == 401
        assert c.post(base + "/" + record["id"] + "/analyse", headers=headers).status_code == 401


def test_analysis_persists_and_repeats(workflow):
    c, base, directory = workflow
    record = upload(c, base).json()
    url = base + "/" + record["id"]
    assert c.get(url + "/observations", headers=HEADERS).json() == []
    response = c.post(url + "/analyse", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["provider"] == "mock"
    assert response.json()["mock"] is True
    fresh = client_for(directory)
    rows = fresh.get(url + "/observations", headers=HEADERS).json()
    assert len(rows) == 1
    assert rows[0]["structured_data"]["mock"] is True
    assert rows[0]["processed_at"]
    assert rows[0]["error"] is None
    assert fresh.get(url, headers=HEADERS).json()["processing_status"] == "ready"
    assert fresh.post(url + "/analyse", headers=HEADERS).status_code == 200
    assert len(c.get(url + "/observations", headers=HEADERS).json()) == 2


@pytest.mark.parametrize("invalid_result", [False, True])
def test_failure_no_fallback_or_secret_leak(workflow, invalid_result):
    c, base, _ = workflow
    record = upload(c, base).json()

    class Broken:
        def describe(self, **kwargs):
            if invalid_result:
                return {"objects_certain": "wrong schema"}
            raise RuntimeError("SECRET that must not appear")

    c.app.dependency_overrides[get_local_vision] = lambda: Broken()
    url = base + "/" + record["id"]
    result = c.post(url + "/analyse", headers=HEADERS)
    assert result.status_code == 502
    rows = c.get(url + "/observations", headers=HEADERS).json()
    assert rows[0]["status"] == "failed"
    assert rows[0]["structured_data"] is None
    assert "SECRET" not in str(rows)
    assert c.get(url, headers=HEADERS).json()["processing_status"] == "failed"
    c.app.dependency_overrides.clear()
    assert c.post(url + "/analyse", headers=HEADERS).status_code == 200
    assert len(c.get(url + "/observations", headers=HEADERS).json()) == 2


def test_adapter_receives_stored_bytes_without_open_transaction(workflow):
    c, base, directory = workflow
    data = image_bytes()
    record = upload(c, base, data).json()

    class Recording:
        def describe(self, *, document_url, text_hint):
            assert base64.b64decode(document_url.split(",")[1]) == data
            # A second writer can commit during inference.
            from app.integrated import connect

            with connect(directory / "projects.sqlite3") as db:
                db.execute("UPDATE projects SET description=?", ("during inference",))
            return {
                "objects_certain": [],
                "objects_possible": [],
                "activities_certain": [],
                "activities_possible": [],
            }

    c.app.dependency_overrides[get_local_vision] = lambda: Recording()
    assert c.post(base + "/" + record["id"] + "/analyse", headers=HEADERS).status_code == 200


def test_real_provider_selection_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="no fallback"):
        create_local_app(
            LocalSettings(
                enabled=True, access_token=TOKEN, data_dir=tmp_path, vision_provider="unknown"
            )
        )


def test_concurrent_attempt_rejected_and_stored_corruption_fails(workflow):
    c, base, directory = workflow
    record = upload(c, base).json()
    url = base + "/" + record["id"]

    class Concurrent:
        def describe(self, **kwargs):
            assert c.post(url + "/analyse", headers=HEADERS).status_code == 409
            return {
                "objects_certain": [],
                "objects_possible": [],
                "activities_certain": [],
                "activities_possible": [],
            }

    c.app.dependency_overrides[get_local_vision] = lambda: Concurrent()
    assert c.post(url + "/analyse", headers=HEADERS).status_code == 200
    assert len(c.get(url + "/observations", headers=HEADERS).json()) == 1
    # Simulate local disk corruption, not a provider success.
    (directory / record["stored_filename"]).write_bytes(b"corrupt")
    assert c.post(url + "/analyse", headers=HEADERS).status_code == 502
    assert c.get(url + "/observations", headers=HEADERS).json()[-1]["status"] == "failed"
