import json
import sqlite3
from uuid import uuid4

import pytest

from app.integrated import connect
from tests.test_integrated import HEADERS, client_for
from tests.test_local_matching import GROUPS, add_analysis, contract
from tests.test_local_matching import setup as setup  # noqa: F401


def prepared(setup):
    c, pid, item, ev, directory = setup
    obs = add_analysis(directory, ev)
    base = f"/projects/{pid}/matches"
    assert c.post(base + "/generate", headers=HEADERS).status_code == 200
    match = c.get(base, headers=HEADERS).json()[0]
    assert c.post(base + "/" + match["id"] + "/confirm", headers=HEADERS).status_code == 200
    return c, pid, item, ev, directory, obs, match


def package(c, pid):
    response = c.get(f"/projects/{pid}/claim-package.json", headers=HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def test_eligible_package_structure_persistence_and_no_mutation(setup):
    c, pid, item, ev, directory, obs, match = prepared(setup)
    with connect(directory / "projects.sqlite3") as db:
        before = list(db.iterdump())
    result = package(c, pid)
    assert result["status"] == "draft"
    assert result["schema_version"] == "subpay.draft-claim-support.v1"
    assert result["package_id"] and result["generated_at"]
    assert result["project"]["id"] == pid
    assert len(result["contracts"]) == 1
    row = result["contract_items"][0]
    assert row["id"] == item and row["quantity"] is None
    link = row["supporting_evidence"][0]
    assert link["evidence"]["id"] == ev
    assert link["analysis"]["id"] == obs
    assert link["analysis"]["observations"] == GROUPS
    assert link["analysis"]["mock"] is False
    assert link["match"]["reviewed_by"] == "local-development-user"
    assert link["match"]["reviewed_at"]
    assert link["match"]["id"] == match["id"]
    assert result["coverage"]["supported_items"] == 1
    assert result["coverage"]["unlinked_evidence_count"] == 0
    text = json.dumps(result)
    for private in ("storage_path", "stored_filename", "access_token", "api_key", str(directory)):
        assert private not in text
    again = package(client_for(directory), pid)
    assert again["contract_items"] == result["contract_items"]
    html = c.get(f"/projects/{pid}/claim-package.html", headers=HEADERS)
    assert html.status_code == 200
    assert "Human-confirmed" in html.text and "Missing evidence" in html.text
    with connect(directory / "projects.sqlite3") as db:
        assert list(db.iterdump()) == before


@pytest.mark.parametrize(
    "case",
    [
        "pending",
        "rejected",
        "reopened",
        "stale",
        "mock",
        "superseded",
        "empty",
        "unconfirmed",
    ],
)
def test_ineligible_links_excluded(setup, case):
    c, pid, item, ev, directory, obs, match = prepared(setup)
    url = f"/projects/{pid}/matches/{match['id']}"
    if case in ("pending", "rejected", "reopened"):
        c.post(url + "/reopen", headers=HEADERS)
        if case == "rejected":
            c.post(url + "/reject", headers=HEADERS)
    elif case in ("mock", "superseded", "empty"):
        if case == "mock":
            with connect(directory / "projects.sqlite3") as db:
                data = json.loads(
                    db.execute(
                        "SELECT structured_data FROM local_observations WHERE id=?",
                        (obs,),
                    ).fetchone()[0]
                )
                data["mock"] = True
                db.execute(
                    "UPDATE local_observations SET structured_data=? WHERE id=?",
                    (json.dumps(data), obs),
                )
        else:
            add_analysis(directory, ev, {k: [] for k in GROUPS} if case == "empty" else GROUPS)
    else:
        with connect(directory / "projects.sqlite3") as db:
            if case == "stale":
                db.execute(
                    "UPDATE local_contract_items SET description=? WHERE id=?",
                    ("Changed distribution board description", item),
                )
            else:
                db.execute(
                    "UPDATE local_contract_items SET review_status='draft' WHERE id=?", (item,)
                )
    result = package(c, pid)
    assert result["coverage"]["supported_items"] == 0
    assert all(not i["supporting_evidence"] for i in result["contract_items"])
    assert result["coverage"]["unlinked_evidence_count"] == 1


def test_zero_support_and_coverage(setup):
    c, pid, _, _, _ = setup
    result = package(c, pid)
    assert result["coverage"]["total_confirmed_items"] == 1
    assert result["coverage"]["unsupported_items"] == 1
    assert len(result["coverage"]["unsupported_item_ids"]) == 1
    empty = c.post("/projects", headers=HEADERS, json={"name": "Empty"}).json()["id"]
    result = package(c, empty)
    assert result["contract_items"] == [] and result["coverage"]["supported_items"] == 0


@pytest.mark.parametrize("extension", ["json", "html"])
def test_isolation_auth_ids_and_download_headers(setup, extension):
    c, pid, _, _, _, _, _ = prepared(setup)
    other = c.post("/projects", headers=HEADERS, json={"name": "Other"}).json()["id"]
    contract(c, other, "Install electrical distribution board")
    result = package(c, other)
    assert result["coverage"]["supported_items"] == 0
    assert pid not in json.dumps(result)
    base = f"/projects/{pid}/claim-package.{extension}"
    response = c.get(base, headers=HEADERS)
    expected = "application/json" if extension == "json" else "text/html"
    assert response.headers["content-type"].startswith(expected)
    assert response.headers["content-disposition"] == (
        f'attachment; filename="subpay-{pid}-draft.{extension}"'
    )
    assert response.headers["cache-control"] == "no-store"
    assert c.get(base).status_code == 401
    assert c.get(base, headers={**HEADERS, "Origin": "https://example.com"}).status_code == 403
    assert (
        c.get(f"/projects/{uuid4()}/claim-package.{extension}", headers=HEADERS).status_code == 404
    )
    assert c.get(f"/projects/invalid/claim-package.{extension}", headers=HEADERS).status_code == 422


def test_html_escaping_and_no_external_resources(setup):
    c, pid, _, _, directory, _, _ = prepared(setup)
    attack = '<script>alert("x")</script><img src="https://example.com/x">'
    with connect(directory / "projects.sqlite3") as db:
        db.execute("UPDATE projects SET name=? WHERE id=?", (attack, pid))
        db.execute("UPDATE local_matches SET explanation=?,reviewed_by=?", (attack, attack))
        db.execute("UPDATE local_evidence SET original_filename=?", (attack,))
    response = c.get(f"/projects/{pid}/claim-package.html", headers=HEADERS)
    assert "<script>" not in response.text and "<img " not in response.text
    assert "&lt;script&gt;" in response.text
    assert "&quot;" in response.text
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert "@media print" in response.text


def test_read_snapshot_consistency(setup, monkeypatch):
    from app import local_packages

    c, pid, _, _, directory, _, match = prepared(setup)
    path = directory / "projects.sqlite3"
    with sqlite3.connect(path) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
    original = local_packages.current

    def concurrent_review(db, row):
        with sqlite3.connect(path) as writer:
            writer.execute(
                "UPDATE local_matches SET review_status='pending',"
                "reviewed_by=NULL,reviewed_at=NULL WHERE id=?",
                (match["id"],),
            )
        return original(db, row)

    monkeypatch.setattr(local_packages, "current", concurrent_review)
    assert package(c, pid)["coverage"]["supported_items"] == 1
    monkeypatch.setattr(local_packages, "current", original)
    assert package(c, pid)["coverage"]["supported_items"] == 0


def test_fresh_project_without_other_tables(tmp_path):
    c = client_for(tmp_path)
    pid = c.post("/projects", headers=HEADERS, json={"name": "Fresh"}).json()["id"]
    assert package(c, pid)["contracts"] == []
