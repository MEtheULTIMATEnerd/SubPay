"""Evidence capture, upload, the library, editing, archiving and AI processing (F06, F07)."""

import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.ai.evidence import MockEvidenceProcessor
from app.core import errors
from tests.conftest import MEMBER_A_ID, USER_B_ID, USER_ID
from tests.fakes import FakeDatabase, FakeStorage
from tests.files import (
    DOCX_MIME,
    HEIC_BYTES,
    JPEG_BYTES,
    PDF_BYTES,
    PNG_BYTES,
    WEBP_BYTES,
    XLSX_MIME,
    docx_bytes,
    xlsx_bytes,
    zip_bytes,
)

Headers = Callable[..., dict[str, str]]
API = "/api/v1"


def new_project(client: TestClient, headers: dict[str, str], name: str = "Hume St Tower") -> str:
    response = client.post(
        f"{API}/projects", json={"name": name, "client_name": "Bellrock"}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def add(
    client: TestClient,
    headers: dict[str, str],
    project_id: str,
    *,
    file: tuple[str, bytes, str] | None = ("IMG_2041.jpg", JPEG_BYTES, "image/jpeg"),
    **fields: Any,
):
    if "metadata" in fields and not isinstance(fields["metadata"], str):
        fields["metadata"] = json.dumps(fields["metadata"])
    return client.post(
        f"{API}/projects/{project_id}/evidence",
        files={"file": file} if file else None,
        data=fields,
        headers=headers,
    )


def added(client: TestClient, headers: dict[str, str], project_id: str, **kwargs: Any) -> dict:
    response = add(client, headers, project_id, **kwargs)
    assert response.status_code == 201, response.text
    return response.json()


def listed(client: TestClient, headers: dict[str, str], project_id: str, **query: Any) -> list:
    response = client.get(f"{API}/projects/{project_id}/evidence", params=query, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["items"]


@pytest.fixture
def project_a(client: TestClient, as_user: Headers) -> str:
    return new_project(client, as_user())


# ---- authentication -----------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", f"{API}/projects/{uuid4()}/evidence"),
        ("GET", f"{API}/projects/{uuid4()}/evidence"),
        ("GET", f"{API}/evidence/{uuid4()}"),
        ("PATCH", f"{API}/evidence/{uuid4()}"),
        ("POST", f"{API}/evidence/{uuid4()}/process"),
    ],
)
def test_every_evidence_endpoint_requires_authentication(
    client: TestClient, storage: FakeStorage, db: FakeDatabase, method: str, path: str
) -> None:
    response = client.request(method, path, files={"file": ("a.jpg", JPEG_BYTES)})
    assert response.status_code == 401
    assert storage.files == {}
    assert db.evidence == {}


# ---- upload -------------------------------------------------------------------


def test_upload_stores_the_file_and_records_the_evidence(
    client: TestClient, as_user: Headers, project_a: str, storage: FakeStorage, db: FakeDatabase
) -> None:
    response = add(
        client,
        as_user(),
        project_a,
        title="Level 3 slab pour",
        description="East side poured, north side formwork in place.",
        evidence_type="photo",
        captured_at="2026-09-14T11:30:00+10:00",
        metadata={"location": "Level 3 east", "source": "mobile_upload", "tags": ["slab"]},
    )
    assert response.status_code == 201, response.text
    evidence = response.json()

    assert evidence["project_id"] == project_a
    assert evidence["code"] == "EV-001"
    assert evidence["sequence_number"] == 1
    assert evidence["uploaded_by"] == USER_ID
    assert evidence["title"] == "Level 3 slab pour"
    assert evidence["description"] == "East side poured, north side formwork in place."
    assert evidence["evidence_type"] == "photo"
    assert evidence["captured_at"] == "2026-09-14T01:30:00Z"
    assert evidence["metadata"] == {
        "location": "Level 3 east",
        "source": "mobile_upload",
        "tags": ["slab"],
    }
    assert evidence["original_filename"] == "IMG_2041.jpg"
    assert evidence["mime_type"] == "image/jpeg"
    assert evidence["size_bytes"] == len(JPEG_BYTES)
    assert evidence["archived"] is False
    assert evidence["processing_status"] == "processing"

    path = f"{project_a}/{evidence['id']}/original.jpg"
    assert evidence["storage_path"] == f"evidence/{path}"
    assert storage.files == {("evidence", path): (JPEG_BYTES, "image/jpeg")}
    assert evidence["preview_url"].startswith(f"https://storage.test/evidence/{path}?")

    # The background task has run by the time the test client returns.
    assert db.evidence[UUID(evidence["id"])]["processing_status"] == "ready"


@pytest.mark.parametrize(
    ("filename", "content", "sent_type", "mime_type", "extension", "evidence_type", "preview"),
    [
        ("a.jpg", JPEG_BYTES, "image/jpeg", "image/jpeg", "jpg", "photo", True),
        ("a.png", PNG_BYTES, "image/png", "image/png", "png", "photo", True),
        ("a.webp", WEBP_BYTES, "image/webp", "image/webp", "webp", "photo", True),
        ("a.HEIC", HEIC_BYTES, "image/heic", "image/heic", "heic", "photo", False),
        ("docket.pdf", PDF_BYTES, "application/pdf", "application/pdf", "pdf", "document", False),
        ("letter.docx", docx_bytes(), DOCX_MIME, DOCX_MIME, "docx", "document", False),
        ("hours.xlsx", xlsx_bytes(), XLSX_MIME, XLSX_MIME, "xlsx", "document", False),
        ("notes.txt", b"Poured 14 Sept.\n", "text/plain", "text/plain", "txt", "document", False),
        ("log.csv", b"day,hours\nMon,8\n", "text/csv", "text/csv", "csv", "document", False),
    ],
)
def test_each_supported_file_type_is_stored_under_a_server_chosen_name(
    client: TestClient,
    as_user: Headers,
    project_a: str,
    storage: FakeStorage,
    filename: str,
    content: bytes,
    sent_type: str,
    mime_type: str,
    extension: str,
    evidence_type: str,
    preview: bool,
) -> None:
    evidence = added(client, as_user(), project_a, file=(filename, content, sent_type))
    assert evidence["mime_type"] == mime_type
    assert evidence["evidence_type"] == evidence_type
    assert evidence["title"] == filename
    assert evidence["storage_path"].endswith(f"/{evidence['id']}/original.{extension}")
    assert (evidence["preview_url"] is not None) is preview
    assert len(storage.files) == 1


def test_the_type_comes_from_the_contents_not_the_name_or_the_browser(
    client: TestClient, as_user: Headers, project_a: str
) -> None:
    """A PNG named .pdf and labelled as a PDF is stored as the PNG it is."""
    evidence = added(client, as_user(), project_a, file=("scan.pdf", PNG_BYTES, "application/pdf"))
    assert evidence["mime_type"] == "image/png"
    assert evidence["storage_path"].endswith("original.png")
    assert evidence["original_filename"] == "scan.pdf"


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("virus.exe", b"MZ\x90\x00" + b"\x00" * 60),
        ("archive.zip", zip_bytes()),
        ("page.html", b"<html><script>alert(1)</script></html>"),
        ("photo.jpg", b"<html>not a photo</html>"),
        ("notes.txt", b"\x00\x01\x02 binary pretending to be text \xff\xfe"),
        ("clip.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32),
    ],
)
def test_unsupported_files_are_refused_and_nothing_is_stored(
    client: TestClient,
    as_user: Headers,
    project_a: str,
    storage: FakeStorage,
    db: FakeDatabase,
    filename: str,
    content: bytes,
) -> None:
    response = add(client, as_user(), project_a, file=(filename, content, "image/jpeg"))
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"
    assert storage.files == {}
    assert db.evidence == {}


def test_a_dangerous_filename_is_display_only(
    client: TestClient, as_user: Headers, project_a: str, storage: FakeStorage
) -> None:
    evidence = added(
        client, as_user(), project_a, file=("../../etc/passwd.jpg", JPEG_BYTES, "image/jpeg")
    )
    assert evidence["original_filename"] == "passwd.jpg"
    ((bucket, path),) = storage.files
    assert (bucket, path) == ("evidence", f"{project_a}/{evidence['id']}/original.jpg")


def test_a_written_note_needs_no_file(
    client: TestClient, as_user: Headers, project_a: str, storage: FakeStorage
) -> None:
    evidence = added(
        client,
        as_user(),
        project_a,
        file=None,
        description="Site super confirmed by phone that the north wall is complete.",
    )
    assert evidence["storage_path"] is None
    assert evidence["original_filename"] is None
    assert evidence["mime_type"] is None
    assert evidence["size_bytes"] is None
    assert evidence["preview_url"] is None
    assert evidence["title"] == "Note"
    assert evidence["evidence_type"] == "message"
    assert storage.files == {}


@pytest.mark.parametrize("description", [None, "", "   \n "])
def test_evidence_needs_a_file_or_a_note(
    client: TestClient, as_user: Headers, project_a: str, db: FakeDatabase, description: str | None
) -> None:
    fields = {} if description is None else {"description": description}
    response = add(client, as_user(), project_a, file=None, title="Nothing here", **fields)
    assert response.status_code == 422
    assert response.json()["error"]["details"] == [
        {"field": "description", "message": "Add a file or a written note"}
    ]
    assert db.evidence == {}


def test_an_empty_file_is_refused(client: TestClient, as_user: Headers, project_a: str) -> None:
    response = add(client, as_user(), project_a, file=("empty.jpg", b"", "image/jpeg"))
    assert response.status_code == 422
    assert response.json()["error"]["details"] == [
        {"field": "file", "message": "The file is empty"}
    ]


def test_a_file_over_the_limit_is_refused(
    client: TestClient,
    as_user: Headers,
    project_a: str,
    storage: FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.api.v1.evidence.MAX_EVIDENCE_BYTES", 1024 * 1024)
    big = JPEG_BYTES + b"\x00" * (1024 * 1024)
    response = add(client, as_user(), project_a, file=("big.jpg", big, "image/jpeg"))
    assert response.status_code == 413
    assert response.json()["error"]["message"] == "Evidence files must be 1 MB or smaller"
    assert storage.files == {}


@pytest.mark.parametrize(
    ("fields", "field"),
    [
        ({"title": "x" * 201}, "title"),
        ({"description": "x" * 5001}, "description"),
        ({"evidence_type": "video"}, "evidence_type"),
        ({"captured_at": "yesterday"}, "captured_at"),
        ({"captured_at": "2026-09-14T11:30:00"}, "captured_at"),
        ({"metadata": "{not json"}, "metadata"),
        ({"metadata": "[1, 2]"}, "metadata"),
        ({"metadata": json.dumps({"notes": "x" * 10_001})}, "metadata"),
    ],
)
def test_invalid_fields_are_reported_and_nothing_is_stored(
    client: TestClient,
    as_user: Headers,
    project_a: str,
    storage: FakeStorage,
    fields: dict[str, str],
    field: str,
) -> None:
    response = add(client, as_user(), project_a, **fields)
    assert response.status_code == 422, response.text
    assert [d["field"] for d in response.json()["error"]["details"]] == [field]
    assert storage.files == {}


def test_codes_count_up_within_each_project(client: TestClient, as_user: Headers) -> None:
    first, second = new_project(client, as_user()), new_project(client, as_user(), "Second")
    codes = [added(client, as_user(), first)["code"] for _ in range(3)]
    assert codes == ["EV-001", "EV-002", "EV-003"]
    assert added(client, as_user(), second)["code"] == "EV-001"


def test_a_team_member_can_add_evidence_to_their_organisations_project(
    client: TestClient, as_user: Headers, project_a: str
) -> None:
    evidence = added(client, as_user(MEMBER_A_ID), project_a)
    assert evidence["uploaded_by"] == MEMBER_A_ID


def test_storage_failure_records_nothing(
    client: TestClient, as_user: Headers, project_a: str, storage: FakeStorage, db: FakeDatabase
) -> None:
    storage.fail_uploads = True
    response = add(client, as_user(), project_a)
    assert response.status_code == 503
    assert db.evidence == {}


# ---- organisation isolation -----------------------------------------------------


def test_another_organisation_cannot_add_to_or_list_a_project(
    client: TestClient, as_user: Headers, project_a: str, storage: FakeStorage
) -> None:
    added(client, as_user(), project_a)
    before = dict(storage.files)

    response = add(client, as_user(USER_B_ID), project_a)
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Project not found"
    assert storage.files == before

    response = client.get(f"{API}/projects/{project_a}/evidence", headers=as_user(USER_B_ID))
    assert response.status_code == 404


def test_another_organisations_evidence_looks_like_it_does_not_exist(
    client: TestClient, as_user: Headers, project_a: str, db: FakeDatabase
) -> None:
    evidence = added(client, as_user(), project_a, title="Private to org A")
    stranger = as_user(USER_B_ID)
    path = f"{API}/evidence/{evidence['id']}"
    missing = f"{API}/evidence/{uuid4()}"

    for method, url, body in [
        ("GET", path, None),
        ("PATCH", path, {"title": "Taken over"}),
        ("PATCH", path, {"archived": True}),
        ("POST", f"{path}/process", None),
    ]:
        response = client.request(method, url, json=body, headers=stranger)
        assert response.status_code == 404, (method, url)
        assert (
            response.json()
            == client.request(
                method, url.replace(path, missing), json=body, headers=stranger
            ).json()
        )

    row = db.evidence[UUID(evidence["id"])]
    assert row["title"] == "Private to org A"
    assert row["archived"] is False


# ---- the library ----------------------------------------------------------------


@pytest.fixture
def library(client: TestClient, as_user: Headers, project_a: str) -> dict[str, dict]:
    headers = as_user()
    return {
        "slab": added(
            client,
            headers,
            project_a,
            title="Level 3 slab pour",
            description="East side poured.",
            captured_at="2026-09-14T01:30:00Z",
        ),
        "docket": added(
            client,
            headers,
            project_a,
            file=("Docket_88213.pdf", PDF_BYTES, "application/pdf"),
            title="Concrete delivery docket",
            evidence_type="docket",
            captured_at="2026-09-15T23:30:00Z",
        ),
        "note": added(
            client,
            headers,
            project_a,
            file=None,
            description="Super confirmed 100% of the north wall by phone.",
            captured_at="2026-09-16T00:00:00Z",
        ),
    }


def codes(items: list[dict]) -> list[str]:
    return [item["code"] for item in items]


def test_the_library_lists_newest_capture_first_with_previews_for_photos(
    client: TestClient, as_user: Headers, project_a: str, library: dict, storage: FakeStorage
) -> None:
    storage.batch_sign_calls.clear()
    items = listed(client, as_user(), project_a)
    assert codes(items) == ["EV-003", "EV-002", "EV-001"]

    previews = {item["code"]: item["preview_url"] for item in items}
    assert previews["EV-002"] is None and previews["EV-003"] is None
    assert previews["EV-001"].endswith("expires=3600")
    # One storage request signs the whole page, and only the photos.
    assert storage.batch_sign_calls == [[f"{project_a}/{library['slab']['id']}/original.jpg"]]
    assert "download_url" not in items[0]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ({"q": "slab"}, ["EV-001"]),
        ({"q": "SLAB"}, ["EV-001"]),
        ({"q": "north wall"}, ["EV-003"]),
        ({"q": "ev-002"}, ["EV-002"]),
        ({"q": "docket_88213"}, ["EV-002"]),
        ({"q": "100%"}, ["EV-003"]),
        ({"q": "nothing matches this"}, []),
        ({"q": "   "}, ["EV-003", "EV-002", "EV-001"]),
        ({"evidence_type": "docket"}, ["EV-002"]),
        ({"evidence_type": "photo"}, ["EV-001"]),
        ({"from": "2026-09-15"}, ["EV-003", "EV-002"]),
        ({"to": "2026-09-15"}, ["EV-002", "EV-001"]),
        ({"from": "2026-09-15", "to": "2026-09-15"}, ["EV-002"]),
        ({"from": "2026-09-17"}, []),
        ({"archived": "false"}, ["EV-003", "EV-002", "EV-001"]),
        ({"archived": "true"}, []),
        ({"limit": 2}, ["EV-003", "EV-002"]),
        ({"limit": 2, "offset": 2}, ["EV-001"]),
        ({"q": "confirmed", "evidence_type": "message", "from": "2026-09-16"}, ["EV-003"]),
    ],
)
def test_the_library_can_be_searched_and_filtered(
    client: TestClient,
    as_user: Headers,
    project_a: str,
    library: dict,
    query: dict[str, Any],
    expected: list[str],
) -> None:
    assert codes(listed(client, as_user(), project_a, **query)) == expected


@pytest.mark.parametrize(
    "query",
    [
        {"evidence_type": "video"},
        {"from": "14/09/2026"},
        {"archived": "maybe"},
        {"limit": 0},
        {"limit": 201},
        {"offset": -1},
        {"q": "x" * 201},
    ],
)
def test_invalid_filters_are_rejected(
    client: TestClient, as_user: Headers, project_a: str, query: dict[str, Any]
) -> None:
    response = client.get(f"{API}/projects/{project_a}/evidence", params=query, headers=as_user())
    assert response.status_code == 422


def test_the_library_only_shows_the_projects_own_evidence(
    client: TestClient, as_user: Headers, project_a: str, library: dict
) -> None:
    other = new_project(client, as_user(), "Second project")
    added(client, as_user(), other, title="Belongs to the second project")
    assert len(listed(client, as_user(), project_a)) == 3
    assert [item["title"] for item in listed(client, as_user(), other)] == [
        "Belongs to the second project"
    ]


def test_the_library_still_lists_evidence_when_previews_cannot_be_signed(
    client: TestClient,
    as_user: Headers,
    project_a: str,
    library: dict,
    storage: FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def down(*args: Any, **kwargs: Any) -> dict[str, str]:
        raise errors.service_unavailable()

    monkeypatch.setattr(storage, "signed_urls", down)
    items = listed(client, as_user(), project_a)
    assert len(items) == 3
    assert all(item["preview_url"] is None for item in items)


# ---- one record -----------------------------------------------------------------


def test_one_record_comes_with_a_short_lived_download_link(
    client: TestClient, as_user: Headers, project_a: str, library: dict
) -> None:
    response = client.get(f"{API}/evidence/{library['docket']['id']}", headers=as_user())
    assert response.status_code == 200
    detail = response.json()
    assert detail["code"] == "EV-002"
    assert detail["download_url"].endswith("expires=300")
    assert detail["preview_url"] is None

    note = client.get(f"{API}/evidence/{library['note']['id']}", headers=as_user()).json()
    assert note["download_url"] is None


def test_a_malformed_id_is_a_validation_error(client: TestClient, as_user: Headers) -> None:
    assert client.get(f"{API}/evidence/not-a-uuid", headers=as_user()).status_code == 422


# ---- editing --------------------------------------------------------------------


def test_details_can_be_edited_without_touching_the_file(
    client: TestClient, as_user: Headers, project_a: str, library: dict, storage: FakeStorage
) -> None:
    before = dict(storage.files)
    original = library["slab"]
    response = client.patch(
        f"{API}/evidence/{original['id']}",
        json={
            "title": "  Level 3 slab pour (east)  ",
            "description": "East side poured and finished.",
            "evidence_type": "document",
            "captured_at": "2026-09-14T03:00:00+10:00",
            "metadata": {"location": "Level 3", "tags": ["slab", "pour"]},
        },
        headers=as_user(MEMBER_A_ID),
    )
    assert response.status_code == 200, response.text
    edited = response.json()
    assert edited["title"] == "Level 3 slab pour (east)"
    assert edited["description"] == "East side poured and finished."
    assert edited["evidence_type"] == "document"
    assert edited["captured_at"] == "2026-09-13T17:00:00Z"
    assert edited["metadata"] == {"location": "Level 3", "tags": ["slab", "pour"]}

    for unchanged in (
        "id",
        "code",
        "storage_path",
        "original_filename",
        "uploaded_by",
        "size_bytes",
    ):
        assert edited[unchanged] == original[unchanged]
    assert storage.files == before


def test_server_owned_fields_cannot_be_changed(
    client: TestClient, as_user: Headers, project_a: str, library: dict, db: FakeDatabase
) -> None:
    original = library["slab"]
    response = client.patch(
        f"{API}/evidence/{original['id']}",
        json={
            "title": "Renamed",
            "code": "EV-999",
            "storage_path": "evidence/somewhere/else/original.jpg",
            "project_id": str(uuid4()),
            "uploaded_by": USER_B_ID,
            "processing_status": "failed",
            "original_filename": "other.jpg",
        },
        headers=as_user(),
    )
    assert response.status_code == 200
    edited = response.json()
    assert edited["title"] == "Renamed"
    for field in ("code", "storage_path", "project_id", "uploaded_by", "original_filename"):
        assert edited[field] == original[field]
    assert db.evidence[UUID(original["id"])]["processing_status"] == "ready"


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({}, "Send at least one field to update"),
        ({"code": "EV-999"}, "Send at least one field to update"),
        ({"title": None}, "title cannot be null"),
        ({"title": "   "}, None),
        ({"title": "x" * 201}, None),
        ({"description": "x" * 5001}, None),
        ({"evidence_type": "video"}, None),
        ({"captured_at": "last tuesday"}, None),
        ({"captured_at": "2026-09-14T11:30:00"}, None),
        ({"metadata": ["not", "an", "object"]}, None),
        ({"metadata": {"notes": "x" * 10_001}}, "metadata is too large"),
        ({"archived": "sometimes"}, None),
    ],
)
def test_invalid_edits_are_rejected_and_nothing_changes(
    client: TestClient,
    as_user: Headers,
    project_a: str,
    library: dict,
    db: FakeDatabase,
    body: dict[str, Any],
    message: str | None,
) -> None:
    evidence_id = library["slab"]["id"]
    before = dict(db.evidence[UUID(evidence_id)])
    response = client.patch(f"{API}/evidence/{evidence_id}", json=body, headers=as_user())
    assert response.status_code == 422, response.text
    if message:
        assert message in [d["message"] for d in response.json()["error"]["details"]]
    assert db.evidence[UUID(evidence_id)] == before


def test_a_note_cannot_be_edited_down_to_nothing(
    client: TestClient, as_user: Headers, project_a: str, library: dict
) -> None:
    response = client.patch(
        f"{API}/evidence/{library['note']['id']}", json={"description": "  "}, headers=as_user()
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"] == [
        {"field": "description", "message": "Add a file or a written note"}
    ]
    # Evidence with a file may have an empty description.
    response = client.patch(
        f"{API}/evidence/{library['docket']['id']}", json={"description": ""}, headers=as_user()
    )
    assert response.status_code == 200
    assert response.json()["description"] == ""


# ---- archiving ------------------------------------------------------------------


def test_evidence_is_archived_and_restored_never_deleted(
    client: TestClient,
    as_user: Headers,
    project_a: str,
    library: dict,
    storage: FakeStorage,
    db: FakeDatabase,
) -> None:
    headers = as_user()
    path = f"{API}/evidence/{library['slab']['id']}"
    files_before = dict(storage.files)

    response = client.patch(path, json={"archived": True}, headers=headers)
    assert response.status_code == 200
    assert response.json()["archived"] is True

    assert codes(listed(client, headers, project_a, archived="false")) == ["EV-003", "EV-002"]
    assert codes(listed(client, headers, project_a, archived="true")) == ["EV-001"]
    assert len(listed(client, headers, project_a)) == 3
    # Archived evidence keeps its file and can still be opened.
    assert storage.files == files_before
    assert client.get(path, headers=headers).json()["download_url"] is not None

    response = client.patch(path, json={"archived": False}, headers=headers)
    assert response.json()["archived"] is False
    assert len(db.evidence) == 3


def test_there_is_no_way_to_delete_evidence(
    client: TestClient, as_user: Headers, library: dict
) -> None:
    response = client.delete(f"{API}/evidence/{library['slab']['id']}", headers=as_user())
    assert response.status_code == 405


# ---- AI processing ----------------------------------------------------------------


def test_the_ai_service_is_given_the_details_and_a_link_to_the_file(
    client: TestClient,
    as_user: Headers,
    project_a: str,
    processor: MockEvidenceProcessor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = []
    monkeypatch.setattr(processor, "process", requests.append)

    photo = added(
        client,
        as_user(),
        project_a,
        title="Level 3 slab pour",
        description="East side poured.",
        metadata={"location": "Level 3"},
    )
    note = added(client, as_user(), project_a, file=None, description="Phone call with the super.")

    first, second = requests
    assert str(first.evidence_id) == photo["id"]
    assert str(first.project_id) == project_a
    assert first.evidence_type == "photo"
    assert first.title == "Level 3 slab pour"
    assert first.description == "East side poured."
    assert first.metadata == {"location": "Level 3"}
    assert first.original_filename == "IMG_2041.jpg"
    assert first.mime_type == "image/jpeg"
    assert first.document_url.startswith(
        f"https://storage.test/evidence/{project_a}/{photo['id']}/original.jpg?"
    )

    assert str(second.evidence_id) == note["id"]
    assert second.document_url is None
    assert second.mime_type is None


def test_evidence_is_kept_when_the_ai_service_is_down_and_can_be_retried(
    client: TestClient,
    as_user: Headers,
    project_a: str,
    processor: MockEvidenceProcessor,
    storage: FakeStorage,
) -> None:
    headers = as_user()
    processor.available = False
    evidence = added(client, headers, project_a)
    path = f"{API}/evidence/{evidence['id']}"

    stored = client.get(path, headers=headers).json()
    assert stored["processing_status"] == "failed"
    assert stored["download_url"] is not None
    assert len(storage.files) == 1

    # Still down: the retry is accepted and fails again.
    response = client.post(f"{path}/process", headers=headers)
    assert response.status_code == 200
    assert response.json()["processing_status"] == "processing"
    assert client.get(path, headers=headers).json()["processing_status"] == "failed"

    processor.available = True
    response = client.post(f"{path}/process", headers=as_user(MEMBER_A_ID))
    assert response.status_code == 200
    assert client.get(path, headers=headers).json()["processing_status"] == "ready"
    assert len(storage.files) == 1


def test_an_unexpected_processing_error_is_recorded_as_failed(
    client: TestClient,
    as_user: Headers,
    project_a: str,
    processor: MockEvidenceProcessor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(request: Any) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(processor, "process", explode)
    evidence = added(client, as_user(), project_a)
    stored = client.get(f"{API}/evidence/{evidence['id']}", headers=as_user()).json()
    assert stored["processing_status"] == "failed"


def test_processed_evidence_cannot_be_sent_again(
    client: TestClient, as_user: Headers, project_a: str
) -> None:
    evidence = added(client, as_user(), project_a)
    response = client.post(f"{API}/evidence/{evidence['id']}/process", headers=as_user())
    assert response.status_code == 409
    assert response.json()["error"]["message"] == "This evidence has already been processed"


def test_evidence_still_processing_can_only_be_retried_once_it_is_stuck(
    client: TestClient, as_user: Headers, project_a: str, db: FakeDatabase
) -> None:
    evidence = added(client, as_user(), project_a)
    row = db.evidence[UUID(evidence["id"])]
    path = f"{API}/evidence/{evidence['id']}"

    row.update(processing_status="processing", updated_at=datetime.now(timezone.utc))
    response = client.post(f"{path}/process", headers=as_user())
    assert response.status_code == 409
    assert response.json()["error"]["message"] == "This evidence is still being processed"

    row.update(updated_at=datetime.now(timezone.utc) - timedelta(minutes=11))
    assert client.post(f"{path}/process", headers=as_user()).status_code == 200
    assert client.get(path, headers=as_user()).json()["processing_status"] == "ready"


def test_evidence_left_at_uploaded_can_be_processed(
    client: TestClient, as_user: Headers, project_a: str, db: FakeDatabase
) -> None:
    evidence = added(client, as_user(), project_a)
    db.evidence[UUID(evidence["id"])]["processing_status"] = "uploaded"
    path = f"{API}/evidence/{evidence['id']}"
    assert client.post(f"{path}/process", headers=as_user()).status_code == 200
    assert client.get(path, headers=as_user()).json()["processing_status"] == "ready"


def test_capture_time_defaults_to_now(client: TestClient, as_user: Headers, project_a: str) -> None:
    evidence = added(client, as_user(), project_a)
    captured = datetime.fromisoformat(evidence["captured_at"].replace("Z", "+00:00"))
    assert abs(datetime.now(timezone.utc) - captured) < timedelta(minutes=1)
