"""Evidence at the edges of this API: file-type detection, the queries sent to
Supabase, batch-signed previews and the AI service call."""

import json
from collections.abc import Callable
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import httpx2
import pytest

from app.ai.evidence import EvidenceRequest, HttpEvidenceProcessor, MockEvidenceProcessor
from app.ai.extraction import AiUnavailableError
from app.api.deps import get_evidence_processor
from app.core.config import Settings
from app.core.errors import ApiError
from app.db.storage import SupabaseStorage
from app.db.supabase import SupabaseRest
from app.repositories.evidence import (
    EvidenceFilters,
    SupabaseEvidenceRepository,
    build_filters,
)
from app.services import uploads
from tests.files import (
    HEIC_BYTES,
    JPEG_BYTES,
    PDF_BYTES,
    PNG_BYTES,
    WEBP_BYTES,
    docx_bytes,
    xlsx_bytes,
    zip_bytes,
)

BASE = "https://test-project.supabase.co"
USER_TOKEN = "the-callers-own-access-token"
PROJECT_ID = UUID("aaaaaaaa-0000-4000-8000-000000000001")
EVIDENCE_ID = UUID("eeeeeeee-0000-4000-8000-000000000001")
PATH = f"{PROJECT_ID}/{EVIDENCE_ID}/original.jpg"

EVIDENCE_ROW = {
    "id": str(EVIDENCE_ID),
    "project_id": str(PROJECT_ID),
    "sequence_number": 1,
    "code": "EV-001",
    "uploaded_by": "a0000000-0000-4000-8000-000000000001",
    "storage_path": f"evidence/{PATH}",
    "original_filename": "IMG_2041.jpg",
    "mime_type": "image/jpeg",
    "size_bytes": 2048,
    "evidence_type": "photo",
    "captured_at": "2026-09-14T01:30:00+00:00",
    "title": "Level 3 slab pour",
    "description": "",
    "metadata": {"location": "Level 3"},
    "processing_status": "uploaded",
    "archived": False,
    "created_at": "2026-09-14T01:31:00+00:00",
    "updated_at": "2026-09-14T01:31:00+00:00",
}

Handler = Callable[[httpx2.Request], httpx2.Response]


def recording(handler: Handler) -> tuple[httpx2.Client, list[httpx2.Request]]:
    requests: list[httpx2.Request] = []

    def record(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return handler(request)

    return httpx2.Client(transport=httpx2.MockTransport(record)), requests


def query(request: httpx2.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(str(request.url)).query).items()}


# ---- file-type detection ----------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "data", "kind"),
    [
        ("a.jpg", JPEG_BYTES, uploads.JPEG),
        ("a.bin", JPEG_BYTES, uploads.JPEG),
        ("a.png", PNG_BYTES, uploads.PNG),
        ("a.webp", WEBP_BYTES, uploads.WEBP),
        ("a.heic", HEIC_BYTES, uploads.HEIC),
        ("a.pdf", PDF_BYTES, uploads.PDF),
        ("a.docx", docx_bytes(), uploads.DOCX),
        ("a.xlsx", xlsx_bytes(), uploads.XLSX),
        ("a.txt", "Poured 14 Sept — 32 m³".encode(), uploads.TEXT),
        ("A.CSV", b"day,hours\r\nMon,8\r\n", uploads.CSV),
    ],
)
def test_evidence_kind_recognises_each_supported_type(
    filename: str, data: bytes, kind: uploads.FileKind
) -> None:
    assert uploads.evidence_kind(filename, data) == kind


@pytest.mark.parametrize(
    ("filename", "data"),
    [
        ("a.zip", zip_bytes()),
        ("a.xlsx", zip_bytes()),
        ("a.jpg", b"GIF89a" + b"\x00" * 32),
        ("a.webp", b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 32),
        ("a.heic", b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32),
        ("a.txt", b"\xff\xfe\x00\x01 not text"),
        ("a.txt", b"has a \x00 nul byte"),
        ("a.html", b"<p>plain enough, but not a text file by name</p>"),
        ("a.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>"),
        ("no-extension", b"just some words"),
    ],
)
def test_evidence_kind_refuses_everything_else(filename: str, data: bytes) -> None:
    with pytest.raises(ApiError) as caught:
        uploads.evidence_kind(filename, data)
    assert caught.value.status_code == 415
    assert caught.value.message == uploads.EVIDENCE_TYPES_MESSAGE


# ---- what we ask Supabase for -----------------------------------------------------


def test_no_filters_only_limits_the_query_to_the_project() -> None:
    assert build_filters(PROJECT_ID, EvidenceFilters()) == {"project_id": f"eq.{PROJECT_ID}"}


def test_filters_become_postgrest_parameters() -> None:
    params = build_filters(
        PROJECT_ID,
        EvidenceFilters(
            q="  slab pour ",
            evidence_type="photo",
            captured_from=date(2026, 9, 14),
            captured_to=date(2026, 9, 30),
            archived=False,
        ),
    )
    assert params == {
        "project_id": f"eq.{PROJECT_ID}",
        "evidence_type": "eq.photo",
        "archived": "is.false",
        # "to" is inclusive: everything before the start of the next day.
        "and": '(captured_at.gte."2026-09-14T00:00:00Z",captured_at.lt."2026-10-01T00:00:00Z")',
        "or": (
            '(title.ilike."*slab pour*",description.ilike."*slab pour*",'
            'code.ilike."*slab pour*",original_filename.ilike."*slab pour*")'
        ),
    }
    assert build_filters(PROJECT_ID, EvidenceFilters(archived=True))["archived"] == "is.true"


@pytest.mark.parametrize(
    ("typed", "pattern"),
    [
        ("100%", r'"*100\\%*"'),
        ("north_wall", r'"*north\\_wall*"'),
        ("a*b", '"*ab*"'),
        ('say "hi"', r'"*say \"hi\"*"'),
        ("a,b)", '"*a,b)*"'),
        ("back\\slash", r'"*back\\\\slash*"'),
    ],
)
def test_search_text_is_matched_literally(typed: str, pattern: str) -> None:
    """Wildcards and PostgREST syntax in what the user typed cannot change the query."""
    params = build_filters(PROJECT_ID, EvidenceFilters(q=typed))
    assert params["or"].startswith(f"(title.ilike.{pattern},")


def test_the_repository_lists_as_the_caller_newest_capture_first() -> None:
    http, requests = recording(lambda r: httpx2.Response(200, json=[EVIDENCE_ROW]))
    rest = SupabaseRest(http, base_url=BASE, anon_key="anon-key", access_token=USER_TOKEN)
    repository = SupabaseEvidenceRepository(rest)

    records = repository.list_for_project(
        PROJECT_ID, EvidenceFilters(q="slab", limit=20, offset=40)
    )
    assert [r.code for r in records] == ["EV-001"]
    assert records[0].captured_at == datetime(2026, 9, 14, 1, 30, tzinfo=timezone.utc)

    (request,) = requests
    assert request.url.path == "/rest/v1/evidence"
    assert request.headers["authorization"] == f"Bearer {USER_TOKEN}"
    sent = query(request)
    assert sent["project_id"] == f"eq.{PROJECT_ID}"
    assert sent["order"] == "captured_at.desc,id.asc"
    assert sent["limit"] == "20"
    assert sent["offset"] == "40"
    assert sent["or"].startswith('(title.ilike."*slab*"')


def test_the_repository_sends_only_the_given_columns_and_filters_updates_by_id() -> None:
    http, requests = recording(
        lambda r: httpx2.Response(201 if r.method == "POST" else 200, json=[EVIDENCE_ROW])
    )
    rest = SupabaseRest(http, base_url=BASE, anon_key="anon-key", access_token=USER_TOKEN)
    repository = SupabaseEvidenceRepository(rest)

    values = {"id": str(EVIDENCE_ID), "project_id": str(PROJECT_ID), "title": "Note"}
    repository.create(values)
    repository.update(EVIDENCE_ID, {"archived": True})

    create, update = requests
    assert create.method == "POST"
    assert json.loads(create.content) == values
    assert update.method == "PATCH"
    assert query(update)["id"] == f"eq.{EVIDENCE_ID}"
    assert json.loads(update.content) == {"archived": True}


def test_an_update_that_matches_nothing_is_none() -> None:
    http, _ = recording(lambda r: httpx2.Response(200, json=[]))
    rest = SupabaseRest(http, base_url=BASE, anon_key="anon-key", access_token=USER_TOKEN)
    repository = SupabaseEvidenceRepository(rest)
    assert repository.update(EVIDENCE_ID, {"archived": True}) is None
    assert repository.get(EVIDENCE_ID) is None


@pytest.mark.parametrize(
    ("constraint", "field", "message"),
    [
        ("evidence_file_or_note_check", "description", "Add a file or a written note"),
        ("evidence_title_length", "title", "Title must be 1 to 200 characters"),
        (
            "evidence_description_length",
            "description",
            "Description must be 5000 characters or fewer",
        ),
        ("evidence_metadata_is_object", "metadata", "Metadata must be an object"),
    ],
)
def test_database_constraints_become_field_errors(
    constraint: str, field: str, message: str
) -> None:
    body = {
        "code": "23514",
        "message": f'new row for relation "evidence" violates check constraint "{constraint}"',
    }
    http, _ = recording(lambda r: httpx2.Response(400, json=body))
    rest = SupabaseRest(http, base_url=BASE, anon_key="anon-key", access_token=USER_TOKEN)

    with pytest.raises(ApiError) as caught:
        SupabaseEvidenceRepository(rest).update(EVIDENCE_ID, {"description": ""})
    assert caught.value.status_code == 422
    assert caught.value.details == [{"field": field, "message": message}]


# ---- batch-signed previews ----------------------------------------------------------


def make_storage(handler: Handler) -> tuple[SupabaseStorage, list[httpx2.Request]]:
    http, requests = recording(handler)
    return SupabaseStorage(
        http, base_url=BASE, anon_key="anon-key", access_token=USER_TOKEN
    ), requests


def test_signed_urls_signs_every_path_in_one_request() -> None:
    other = f"{PROJECT_ID}/eeeeeeee-0000-4000-8000-000000000002/original.png"
    hidden = f"{PROJECT_ID}/eeeeeeee-0000-4000-8000-000000000003/original.png"
    answer = [
        {"error": None, "path": PATH, "signedURL": f"/object/sign/evidence/{PATH}?token=one"},
        {"error": None, "path": other, "signedURL": f"/object/sign/evidence/{other}?token=two"},
        {
            "error": "Either the object does not exist or you do not have access to it",
            "path": hidden,
            "signedURL": None,
        },
    ]
    storage, requests = make_storage(lambda r: httpx2.Response(200, json=answer))

    links = storage.signed_urls("evidence", [PATH, other, hidden], expires_in=3600)
    assert links == {
        PATH: f"{BASE}/storage/v1/object/sign/evidence/{PATH}?token=one",
        other: f"{BASE}/storage/v1/object/sign/evidence/{other}?token=two",
    }
    (request,) = requests
    assert request.method == "POST"
    assert str(request.url) == f"{BASE}/storage/v1/object/sign/evidence"
    assert request.headers["authorization"] == f"Bearer {USER_TOKEN}"
    assert json.loads(request.content) == {"expiresIn": 3600, "paths": [PATH, other, hidden]}


def test_signed_urls_makes_no_request_for_no_paths() -> None:
    storage, requests = make_storage(lambda r: httpx2.Response(500))
    assert storage.signed_urls("evidence", [], expires_in=3600) == {}
    assert requests == []


def test_signed_urls_reports_a_storage_outage() -> None:
    storage, _ = make_storage(lambda r: httpx2.Response(503, json={"message": "down"}))
    with pytest.raises(ApiError) as caught:
        storage.signed_urls("evidence", [PATH], expires_in=3600)
    assert caught.value.status_code == 503


# ---- the AI service -----------------------------------------------------------------

REQUEST = EvidenceRequest(
    evidence_id=EVIDENCE_ID,
    project_id=PROJECT_ID,
    evidence_type="photo",
    title="Level 3 slab pour",
    description="East side poured.",
    captured_at=datetime(2026, 9, 14, 1, 30, tzinfo=timezone.utc),
    metadata={"location": "Level 3"},
    original_filename="IMG_2041.jpg",
    mime_type="image/jpeg",
    document_url="https://storage.test/evidence/p/e/original.jpg?token=signed",
)


def http_processor(handler: Handler) -> tuple[HttpEvidenceProcessor, list[httpx2.Request]]:
    http, requests = recording(handler)
    return HttpEvidenceProcessor(http, "http://ai.test/"), requests


def test_the_mock_processor_accepts_everything_until_told_otherwise() -> None:
    processor = MockEvidenceProcessor()
    assert processor.process(REQUEST) is None
    processor.available = False
    with pytest.raises(AiUnavailableError):
        processor.process(REQUEST)


def test_the_http_processor_posts_the_evidence_to_the_ai_service() -> None:
    processor, requests = http_processor(lambda r: httpx2.Response(202, json={"status": "ok"}))
    assert processor.process(REQUEST) is None

    (request,) = requests
    assert request.method == "POST"
    assert str(request.url) == f"http://ai.test/ai/v1/evidence/{EVIDENCE_ID}/understand"
    assert json.loads(request.content) == {
        "evidence_id": str(EVIDENCE_ID),
        "project_id": str(PROJECT_ID),
        "evidence_type": "photo",
        "title": "Level 3 slab pour",
        "description": "East side poured.",
        "captured_at": "2026-09-14T01:30:00Z",
        "metadata": {"location": "Level 3"},
        "original_filename": "IMG_2041.jpg",
        "mime_type": "image/jpeg",
        "document_url": "https://storage.test/evidence/p/e/original.jpg?token=signed",
    }
    # The user's access token is never passed on to the AI service.
    assert "authorization" not in request.headers


def _timeout(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ReadTimeout("too slow", request=request)


def _refused(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ConnectError("connection refused", request=request)


@pytest.mark.parametrize(
    "handler",
    [
        _timeout,
        _refused,
        lambda r: httpx2.Response(500, text="Internal Server Error"),
        lambda r: httpx2.Response(404, json={"detail": "Not Found"}),
    ],
)
def test_any_ai_service_failure_is_one_error(handler: Handler) -> None:
    processor, _ = http_processor(handler)
    with pytest.raises(AiUnavailableError):
        processor.process(REQUEST)


@pytest.mark.parametrize(
    ("configured", "expected"),
    [("mock", MockEvidenceProcessor), ("http", HttpEvidenceProcessor)],
)
def test_the_processor_is_chosen_by_configuration(configured: str, expected: type) -> None:
    settings: Any = Settings(_env_file=None, ai_evidence_provider=configured)
    assert isinstance(get_evidence_processor(settings, httpx2.Client()), expected)
