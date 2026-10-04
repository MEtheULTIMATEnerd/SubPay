"""The demo seed script, run against the in-memory API so it cannot drift from the rules."""

from collections.abc import Callable
from datetime import datetime, timezone
from uuid import UUID

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.ai.extraction import MockExtractionProvider
from app.services import uploads
from scripts import seed_demo
from tests.conftest import USER_B_ID
from tests.fakes import FakeDatabase, FakeStorage

Headers = Callable[..., dict[str, str]]
API = "/api/v1"
NOW = datetime(2026, 10, 4, 3, 0, tzinfo=timezone.utc)


def run(client: TestClient, headers: dict[str, str], log: list[str] | None = None):
    lines = log if log is not None else []
    return seed_demo.seed(
        client, API, headers, now=NOW, sleep=lambda seconds: None, log=lines.append
    )


def test_the_sample_files_are_ones_the_api_accepts() -> None:
    contract = seed_demo.make_pdf(seed_demo.SCHEDULE_LINES)
    assert uploads.contract_kind(seed_demo.CONTRACT_FILENAME, contract) == uploads.PDF
    assert contract.rstrip().endswith(b"%%EOF")

    files = [entry.file for entry in seed_demo.demo_evidence() if entry.file]
    kinds = {uploads.evidence_kind(name, data).extension for name, data, _ in files}
    assert kinds == {"png", "pdf", "csv"}
    assert all(len(data) < 200_000 for _, data, _ in files)


def test_the_seed_builds_the_demo_project_through_the_api(
    client: TestClient, as_user: Headers, db: FakeDatabase, storage: FakeStorage
) -> None:
    log: list[str] = []
    summary = run(client, as_user(), log)
    assert summary is not None
    project_id = UUID(summary["project_id"])

    project = db.projects[project_id]
    assert project["name"] == "Riverside Commercial Fitout"
    assert project["client_name"] == "Northbank Builders"

    # contract: stored, extracted, then reviewed
    (contract,) = [c for c in db.contracts.values() if c["project_id"] == project_id]
    assert contract["processing_status"] == "ready"
    assert ("contracts", f"{project_id}/{contract['id']}/original.pdf") in storage.files
    items = {i["item_code"]: i for i in db.contract_items.values()}
    assert {code: i["review_status"] for code, i in items.items()} == {
        "4.2": "confirmed",
        "4.3": "confirmed",
        "4.5": "confirmed",
        "6.1": "draft",
    }
    assert items["4.5"]["edited_by_human"] is True
    assert items["4.5"]["conditions"] == "Claimable 60% on delivery, 40% on energisation"
    assert items["4.2"]["edited_by_human"] is False

    # evidence: every record processed, files stored, one archived, none in the future
    records = sorted(db.evidence.values(), key=lambda r: r["sequence_number"])
    assert (
        [r["code"] for r in records] == summary["evidence"] == [f"EV-00{n}" for n in range(1, 10)]
    )
    assert {r["processing_status"] for r in records} == {"ready"}
    assert [r["title"] for r in records if r["archived"]] == [
        "Conduit run, Level 2 east corridor (blurred)"
    ]
    assert {r["evidence_type"] for r in records} == {"photo", "docket", "document", "message"}
    assert sum(1 for r in records if r["storage_path"] is None) == 1  # the written note
    stored = [path for bucket, path in storage.files if bucket == "evidence"]
    assert len(stored) == 8 and all(path.startswith(f"{project_id}/") for path in stored)
    # the first four follow the team's agreed example
    assert [(r["code"], r["evidence_type"]) for r in records[:3]] == [
        ("EV-001", "photo"),
        ("EV-002", "photo"),
        ("EV-003", "docket"),
    ]
    assert records[3]["code"] == "EV-004" and "Site instruction" in records[3]["title"]
    assert records[0]["metadata"]["tags"] == ["conduit", "level 2"]
    assert all(str(r["captured_at"]) < NOW.isoformat() for r in records)
    assert all(r["metadata"]["source"] in ("mobile_upload", "desktop_upload") for r in records)

    assert log[0] == 'Created project "Riverside Commercial Fitout"'
    assert "4 items extracted" in log[1]


def test_running_the_seed_again_changes_nothing(
    client: TestClient, as_user: Headers, db: FakeDatabase, storage: FakeStorage
) -> None:
    run(client, as_user())
    before = (len(db.projects), len(db.contracts), len(db.evidence), len(storage.files))

    log: list[str] = []
    assert run(client, as_user(), log) is None
    assert "already exists" in log[0]
    assert (len(db.projects), len(db.contracts), len(db.evidence), len(storage.files)) == before


def test_each_organisation_gets_its_own_copy(
    client: TestClient, as_user: Headers, db: FakeDatabase
) -> None:
    first = run(client, as_user())
    second = run(client, as_user(USER_B_ID))
    assert first and second and first["project_id"] != second["project_id"]
    organisations = {p["organisation_id"] for p in db.projects.values()}
    assert len(organisations) == 2


def test_the_seed_still_adds_evidence_when_extraction_is_down(
    client: TestClient, as_user: Headers, db: FakeDatabase, extractor: MockExtractionProvider
) -> None:
    extractor.available = False
    log: list[str] = []
    summary = run(client, as_user(), log)
    assert summary is not None
    assert summary["contract_items"] == 0 and summary["items_reviewed"] == 0
    assert len(db.evidence) == 9
    assert any("did not finish" in line for line in log)


def test_a_refused_request_stops_the_seed_with_a_readable_message(client: TestClient) -> None:
    with pytest.raises(seed_demo.SeedError, match="Could not list projects: 401"):
        run(client, {"Authorization": "Bearer not-a-token"})


def test_sign_in_returns_the_access_token_and_never_echoes_the_password() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if b"right-password" in request.content:
            return httpx2.Response(200, json={"access_token": "token-123"})
        return httpx2.Response(400, json={"error_code": "invalid_credentials"})

    http = httpx2.Client(transport=httpx2.MockTransport(handler))
    url = "https://test-project.supabase.co"

    token = seed_demo.sign_in(http, url, "anon-key", "ollie@kearneyformwork.test", "right-password")
    assert token == "token-123"
    assert str(seen[0].url) == f"{url}/auth/v1/token?grant_type=password"
    assert seen[0].headers["apikey"] == "anon-key"

    with pytest.raises(seed_demo.SeedError) as caught:
        seed_demo.sign_in(http, url, "anon-key", "ollie@kearneyformwork.test", "wrong-password")
    assert "wrong-password" not in str(caught.value)


def test_the_script_explains_missing_configuration(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.core.config import Settings

    monkeypatch.setattr(seed_demo, "get_settings", lambda: Settings(_env_file=None))
    assert seed_demo.main(["--email", "ollie@kearneyformwork.test"]) == 1
    assert "SUPABASE_URL" in capsys.readouterr().err
