"""Contract upload, storage, extraction and retrieval (F03, F04)."""

from collections.abc import Callable
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.ai.extraction import AI_UNAVAILABLE_MESSAGE, MockExtractionProvider
from tests.conftest import MEMBER_A_ID, USER_B_ID, USER_ID
from tests.fakes import FakeDatabase, FakeStorage
from tests.files import DOCX_MIME, PDF_BYTES, docx_bytes, zip_bytes

Headers = Callable[..., dict[str, str]]
API = "/api/v1"


def new_project(client: TestClient, headers: dict[str, str], name: str = "Hume St Tower") -> str:
    response = client.post(
        f"{API}/projects", json={"name": name, "client_name": "Bellrock"}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def upload(
    client: TestClient,
    headers: dict[str, str],
    project_id: str,
    *,
    filename: str = "Subcontract_HumeSt_Formwork.pdf",
    content: bytes = PDF_BYTES,
    content_type: str = "application/pdf",
):
    return client.post(
        f"{API}/projects/{project_id}/contracts",
        files={"file": (filename, content, content_type)},
        headers=headers,
    )


@pytest.fixture
def project_a(client: TestClient, as_user: Headers) -> str:
    return new_project(client, as_user())


# ---- authentication -----------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", f"{API}/projects/{uuid4()}/contracts"),
        ("GET", f"{API}/projects/{uuid4()}/contracts"),
        ("GET", f"{API}/contracts/{uuid4()}"),
        ("POST", f"{API}/contracts/{uuid4()}/extract"),
        ("GET", f"{API}/contracts/{uuid4()}/items"),
    ],
)
def test_every_contract_endpoint_requires_authentication(
    client: TestClient, storage: FakeStorage, method: str, path: str
) -> None:
    response = client.request(method, path, files={"file": ("a.pdf", PDF_BYTES)})
    assert response.status_code == 401
    assert storage.files == {}


# ---- upload -------------------------------------------------------------------


def test_upload_stores_the_file_and_records_the_contract(
    client: TestClient, as_user: Headers, project_a: str, storage: FakeStorage
) -> None:
    response = upload(client, as_user(), project_a)
    assert response.status_code == 201, response.text
    contract = response.json()

    assert contract["project_id"] == project_a
    assert contract["original_filename"] == "Subcontract_HumeSt_Formwork.pdf"
    assert contract["mime_type"] == "application/pdf"
    assert contract["size_bytes"] == len(PDF_BYTES)
    assert contract["uploaded_by"] == USER_ID
    assert contract["processing_status"] == "processing"  # extraction has been started
    assert contract["error"] is None

    # stored privately under the project's and the contract's own folder
    expected_path = f"{project_a}/{contract['id']}/original.pdf"
    assert contract["storage_path"] == f"contracts/{expected_path}"
    assert storage.files[("contracts", expected_path)] == (PDF_BYTES, "application/pdf")


def test_upload_accepts_word_documents(
    client: TestClient, as_user: Headers, project_a: str, storage: FakeStorage
) -> None:
    content = docx_bytes()
    response = upload(
        client, as_user(), project_a, filename="Contract.DOCX", content=content,
        content_type=DOCX_MIME,
    )  # fmt: skip
    assert response.status_code == 201, response.text
    contract = response.json()
    assert contract["mime_type"] == DOCX_MIME
    assert contract["storage_path"].endswith("/original.docx")
    assert ("contracts", contract["storage_path"].split("/", 1)[1]) in storage.files


def test_the_file_type_is_judged_by_its_contents_not_the_browser(
    client: TestClient, as_user: Headers, project_a: str
) -> None:
    """A browser may send a generic type; a PDF is still a PDF."""
    response = upload(client, as_user(), project_a, content_type="application/octet-stream")
    assert response.status_code == 201
    assert response.json()["mime_type"] == "application/pdf"


@pytest.mark.parametrize(
    ("filename", "content", "content_type"),
    [
        ("malware.exe", b"MZ\x90\x00", "application/x-msdownload"),
        ("renamed.pdf", b"MZ\x90\x00 not really a pdf", "application/pdf"),
        ("renamed.docx", zip_bytes(), DOCX_MIME),
        ("contract.docx", PDF_BYTES, DOCX_MIME),
        ("contract.txt", PDF_BYTES, "application/pdf"),
        ("photo.jpg", b"\xff\xd8\xff\xe0", "image/jpeg"),
        ("no-extension", PDF_BYTES, "application/pdf"),
    ],
)
def test_unsupported_files_are_rejected(
    client: TestClient,
    as_user: Headers,
    project_a: str,
    storage: FakeStorage,
    db: FakeDatabase,
    filename: str,
    content: bytes,
    content_type: str,
) -> None:
    response = upload(
        client, as_user(), project_a, filename=filename, content=content, content_type=content_type
    )
    assert response.status_code == 415
    assert response.json()["error"] == {
        "code": "unsupported_media_type",
        "message": "Only PDF or DOCX contracts are supported",
    }
    assert storage.files == {} and db.contracts == {}


def test_a_contract_over_25_mb_is_rejected(
    client: TestClient, as_user: Headers, project_a: str, storage: FakeStorage, db: FakeDatabase
) -> None:
    too_big = PDF_BYTES + b"0" * (25 * 1024 * 1024)
    response = upload(client, as_user(), project_a, content=too_big)
    assert response.status_code == 413
    assert response.json()["error"]["message"] == "Contract must be 25 MB or smaller"
    assert storage.files == {} and db.contracts == {}


def test_an_empty_file_is_rejected(client: TestClient, as_user: Headers, project_a: str) -> None:
    response = upload(client, as_user(), project_a, content=b"")
    assert response.status_code == 422
    assert response.json()["error"]["details"] == [
        {"field": "file", "message": "The file is empty"}
    ]


def test_a_request_without_a_file_is_rejected(
    client: TestClient, as_user: Headers, project_a: str
) -> None:
    response = client.post(f"{API}/projects/{project_a}/contracts", headers=as_user())
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "file"


def test_the_stored_path_never_uses_the_uploaded_filename(
    client: TestClient, as_user: Headers, project_a: str, storage: FakeStorage
) -> None:
    response = upload(client, as_user(), project_a, filename="../../etc/secret plan.pdf")
    assert response.status_code == 201
    contract = response.json()
    assert contract["original_filename"] == "secret plan.pdf"
    ((bucket, path),) = storage.files
    assert (bucket, path) == ("contracts", f"{project_a}/{contract['id']}/original.pdf")


def test_upload_to_another_organisations_project_is_not_found(
    client: TestClient, as_user: Headers, project_a: str, storage: FakeStorage, db: FakeDatabase
) -> None:
    other = upload(client, as_user(USER_B_ID), project_a)
    missing = upload(client, as_user(USER_B_ID), str(uuid4()))

    assert other.status_code == missing.status_code == 404
    assert other.json() == missing.json()
    assert other.json()["error"] == {"code": "not_found", "message": "Project not found"}
    assert storage.files == {} and db.contracts == {}


def test_if_storage_is_down_nothing_is_recorded(
    client: TestClient, as_user: Headers, project_a: str, storage: FakeStorage, db: FakeDatabase
) -> None:
    storage.fail_uploads = True
    response = upload(client, as_user(), project_a)
    assert response.status_code == 503
    assert db.contracts == {}


# ---- extraction ---------------------------------------------------------------


def test_extraction_saves_the_items_as_drafts_for_review(
    client: TestClient, as_user: Headers, project_a: str
) -> None:
    contract = upload(client, as_user(), project_a).json()

    ready = client.get(f"{API}/contracts/{contract['id']}", headers=as_user()).json()
    assert ready["processing_status"] == "ready"
    assert ready["processed_at"] is not None and ready["error"] is None

    items = client.get(f"{API}/contracts/{contract['id']}/items", headers=as_user()).json()["items"]
    assert [i["item_code"] for i in items] == ["1.1", "2.1", "2.2", "3.1", "5.4"]
    assert [i["sort_order"] for i in items] == [0, 1, 2, 3, 4]

    first = items[1]
    assert first["description"] == "Formwork, slab edges"
    assert (first["quantity"], first["unit"], first["rate"], first["amount"]) == (
        180,
        "m²",
        75,
        13500,
    )
    assert first["extraction_confidence"] == 0.9
    assert first["source_reference"] == "Schedule of rates, item 2.1"

    # nothing is confirmed by the AI
    assert {i["review_status"] for i in items} == {"draft"}
    assert not any(i["edited_by_human"] for i in items)
    assert all(i["reviewed_by"] is None for i in items)

    # fields a contract does not contain stay null
    standing_time = items[4]
    assert standing_time["quantity"] is None and standing_time["amount"] is None
    assert (
        standing_time["notice_requirement"] == "Written direction required within 5 business days"
    )


def test_the_ais_original_answer_is_kept_with_each_item(
    client: TestClient, as_user: Headers, project_a: str
) -> None:
    contract = upload(client, as_user(), project_a, filename="Riverside_Fitout.pdf").json()
    items = client.get(f"{API}/contracts/{contract['id']}/items", headers=as_user()).json()["items"]

    assert [i["item_code"] for i in items] == ["4.2", "4.3", "4.5", "6.1"]
    conduit = items[0]
    assert conduit["extracted_values"] == {
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
        "source_reference": "Schedule of rates, item 4.2",
    }


def test_extraction_is_given_a_link_to_the_stored_document(
    client: TestClient, as_user: Headers, project_a: str, extractor: MockExtractionProvider
) -> None:
    seen = []
    original = extractor.extract

    def spy(request):
        seen.append(request)
        return original(request)

    extractor.extract = spy  # type: ignore[method-assign]
    contract = upload(client, as_user(), project_a).json()

    (request,) = seen
    assert str(request.contract_id) == contract["id"]
    assert request.original_filename == "Subcontract_HumeSt_Formwork.pdf"
    assert request.mime_type == "application/pdf"
    assert request.document_url.startswith(
        f"https://storage.test/contracts/{project_a}/{contract['id']}/original.pdf"
    )


def test_when_the_ai_is_unavailable_the_upload_is_kept_and_marked_failed(
    client: TestClient,
    as_user: Headers,
    project_a: str,
    extractor: MockExtractionProvider,
    storage: FakeStorage,
) -> None:
    extractor.available = False
    response = upload(client, as_user(), project_a)
    assert response.status_code == 201  # the upload itself succeeded

    contract = client.get(f"{API}/contracts/{response.json()['id']}", headers=as_user()).json()
    assert contract["processing_status"] == "failed"
    assert contract["error"] == AI_UNAVAILABLE_MESSAGE
    assert contract["processed_at"] is None
    assert len(storage.files) == 1
    items = client.get(f"{API}/contracts/{contract['id']}/items", headers=as_user()).json()
    assert items == {"items": []}


def test_a_failed_extraction_can_be_retried(
    client: TestClient, as_user: Headers, project_a: str, extractor: MockExtractionProvider
) -> None:
    extractor.available = False
    contract_id = upload(client, as_user(), project_a).json()["id"]

    extractor.available = True
    retry = client.post(f"{API}/contracts/{contract_id}/extract", headers=as_user())
    assert retry.status_code == 200
    assert retry.json()["processing_status"] == "processing"
    assert retry.json()["error"] is None

    contract = client.get(f"{API}/contracts/{contract_id}", headers=as_user()).json()
    assert contract["processing_status"] == "ready"
    items = client.get(f"{API}/contracts/{contract_id}/items", headers=as_user()).json()["items"]
    assert len(items) == 5


def test_an_unexpected_extraction_error_is_recorded_not_raised(
    client: TestClient, as_user: Headers, project_a: str, extractor: MockExtractionProvider
) -> None:
    def explode(request):
        raise RuntimeError("model crashed with a secret stack trace")

    extractor.extract = explode  # type: ignore[method-assign]
    response = upload(client, as_user(), project_a)
    assert response.status_code == 201

    contract = client.get(f"{API}/contracts/{response.json()['id']}", headers=as_user()).json()
    assert contract["processing_status"] == "failed"
    assert contract["error"] == AI_UNAVAILABLE_MESSAGE
    assert "secret" not in contract["error"]


def test_a_finished_extraction_cannot_be_run_again(
    client: TestClient, as_user: Headers, project_a: str
) -> None:
    contract_id = upload(client, as_user(), project_a).json()["id"]
    response = client.post(f"{API}/contracts/{contract_id}/extract", headers=as_user())
    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "conflict",
        "message": "This contract has already been extracted",
    }
    items = client.get(f"{API}/contracts/{contract_id}/items", headers=as_user()).json()["items"]
    assert len(items) == 5  # not duplicated


def test_retrying_keeps_reviewed_items_and_does_not_duplicate_them(
    client: TestClient, as_user: Headers, project_a: str, db: FakeDatabase
) -> None:
    contract_id = upload(client, as_user(), project_a).json()["id"]
    by_code = {
        row["item_code"]: row
        for row in db.contract_items.values()
        if row["contract_id"] == UUID(contract_id)
    }
    # a person confirmed one item and edited another; then processing has to run again
    by_code["2.1"].update(review_status="confirmed", reviewed_by=UUID(USER_ID))
    by_code["2.2"].update(quantity=100, edited_by_human=True)
    db.contracts[UUID(contract_id)].update(processing_status="failed")

    assert (
        client.post(f"{API}/contracts/{contract_id}/extract", headers=as_user()).status_code == 200
    )

    items = client.get(f"{API}/contracts/{contract_id}/items", headers=as_user()).json()["items"]
    assert sorted(i["item_code"] for i in items) == ["1.1", "2.1", "2.2", "3.1", "5.4"]
    kept = {i["item_code"]: i for i in items}
    assert (
        kept["2.1"]["id"] == str(by_code["2.1"]["id"])
        and kept["2.1"]["review_status"] == "confirmed"
    )
    assert kept["2.2"]["quantity"] == 100 and kept["2.2"]["edited_by_human"] is True


def test_a_contract_still_processing_cannot_be_retried_yet(
    client: TestClient, as_user: Headers, project_a: str, db: FakeDatabase
) -> None:
    contract_id = upload(client, as_user(), project_a).json()["id"]
    db.contracts[UUID(contract_id)].update(processing_status="processing")
    response = client.post(f"{API}/contracts/{contract_id}/extract", headers=as_user())
    assert response.status_code == 409
    assert response.json()["error"]["message"] == "This contract is still being processed"


def test_a_contract_stuck_in_processing_can_be_retried(
    client: TestClient, as_user: Headers, project_a: str, db: FakeDatabase
) -> None:
    from datetime import datetime, timedelta, timezone

    contract_id = upload(client, as_user(), project_a).json()["id"]
    db.contracts[UUID(contract_id)].update(
        processing_status="processing",
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=11),
    )
    assert (
        client.post(f"{API}/contracts/{contract_id}/extract", headers=as_user()).status_code == 200
    )


# ---- list and retrieve --------------------------------------------------------


def test_list_shows_the_projects_contracts_newest_first(
    client: TestClient, as_user: Headers, project_a: str
) -> None:
    first = upload(client, as_user(), project_a, filename="first.pdf").json()
    second = upload(client, as_user(MEMBER_A_ID), project_a, filename="second.pdf").json()
    other_project = new_project(client, as_user(), "Other Job")
    upload(client, as_user(), other_project, filename="elsewhere.pdf")

    response = client.get(f"{API}/projects/{project_a}/contracts", headers=as_user())
    assert response.status_code == 200
    items = response.json()["items"]
    assert [c["id"] for c in items] == [second["id"], first["id"]]
    assert {c["processing_status"] for c in items} == {"ready"}
    assert "download_url" not in items[0]


def test_get_contract_includes_a_short_lived_download_link(
    client: TestClient, as_user: Headers, project_a: str
) -> None:
    contract_id = upload(client, as_user(), project_a).json()["id"]
    response = client.get(f"{API}/contracts/{contract_id}", headers=as_user(MEMBER_A_ID))
    assert response.status_code == 200
    url = response.json()["download_url"]
    assert url.startswith(f"https://storage.test/contracts/{project_a}/{contract_id}/original.pdf")
    assert "expires=300" in url


def test_another_organisation_cannot_see_or_touch_the_contract(
    client: TestClient, as_user: Headers, project_a: str
) -> None:
    contract_id = upload(client, as_user(), project_a).json()["id"]
    b = as_user(USER_B_ID)

    listing = client.get(f"{API}/projects/{project_a}/contracts", headers=b)
    detail = client.get(f"{API}/contracts/{contract_id}", headers=b)
    items = client.get(f"{API}/contracts/{contract_id}/items", headers=b)
    retry = client.post(f"{API}/contracts/{contract_id}/extract", headers=b)

    assert listing.status_code == 404 and listing.json()["error"]["message"] == "Project not found"
    for response in (detail, items, retry):
        assert response.status_code == 404
        assert response.json()["error"] == {"code": "not_found", "message": "Contract not found"}
    assert "download_url" not in detail.text

    # B's own project has no contracts
    project_b = new_project(client, b, "B Warehouse")
    assert client.get(f"{API}/projects/{project_b}/contracts", headers=b).json() == {"items": []}


def test_missing_and_malformed_ids(client: TestClient, as_user: Headers) -> None:
    assert client.get(f"{API}/contracts/{uuid4()}", headers=as_user()).status_code == 404
    assert client.get(f"{API}/contracts/not-a-uuid", headers=as_user()).status_code == 422
    assert client.get(f"{API}/projects/{uuid4()}/contracts", headers=as_user()).status_code == 404


# ---- delete -------------------------------------------------------------------


def test_deleting_a_contract_removes_its_items_and_file(
    client: TestClient, as_user: Headers, project_a: str, storage: FakeStorage, db: FakeDatabase
) -> None:
    contract = upload(client, as_user(), project_a).json()
    assert db.contract_items
    url = f"{API}/contracts/{contract['id']}"
    assert client.delete(url, headers=as_user(USER_B_ID)).status_code == 404
    assert client.delete(url, headers=as_user()).status_code == 204
    assert db.contracts == {} and db.contract_items == {} and storage.files == {}
    assert client.get(url, headers=as_user()).status_code == 404
