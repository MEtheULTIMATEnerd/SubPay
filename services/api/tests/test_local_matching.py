import json
import sqlite3
from uuid import uuid4

import httpx2
import pytest

from app.integrated import connect
from app.local_contracts import now
from app.local_matching import schema, score_item
from tests.test_integrated import HEADERS, client_for
from tests.test_local_contracts import pdf
from tests.test_local_evidence import image_bytes

GROUPS = {
    "objects_certain": [
        "Electrical distribution board with circuit breakers",
        "Wiring and cables connected to circuit breakers",
    ],
    "objects_possible": [],
    "activities_certain": [],
    "activities_possible": [],
}


def add_analysis(
    directory, evidence_id, groups=GROUPS, *, mock=False, status="ready", invalid=False
):
    ident = str(uuid4())
    data = {
        "mock": mock,
        "observations": groups,
        "understanding": {
            "evidence_id": evidence_id,
            "confidence": 0.0,
            "signals": {
                "objects": [v for values in groups.values() for v in values],
                "activities": [],
                "other_signals": {"mock": mock, "not_real_vision": mock},
            },
        },
    }
    with connect(directory / "projects.sqlite3") as db:
        schema(db)
        db.execute(
            "INSERT INTO local_observations "
            "(id,evidence_id,provider,model,status,processed_at,structured_data) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                ident,
                evidence_id,
                "mock" if mock else "openai",
                "fixture-model",
                status,
                now(),
                "invalid" if invalid else json.dumps(data),
            ),
        )
        db.execute(
            "UPDATE local_evidence SET processing_status=? WHERE id=?", (status, evidence_id)
        )
    return ident


def contract(c, pid, description, confirmed=True):
    base = f"/projects/{pid}/contracts"
    record = c.post(
        base,
        headers=HEADERS,
        files={"file": ("real.pdf", pdf("1.1 " + description), "application/pdf")},
    ).json()
    item = c.get(base + "/" + record["id"] + "/items", headers=HEADERS).json()[0]
    if confirmed:
        c.post(
            base + "/" + record["id"] + "/items/" + item["id"] + "/review",
            headers=HEADERS,
            json={"status": "confirmed"},
        )
    return record["id"], item["id"]


@pytest.fixture
def setup(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Matching must not call external HTTP")

    monkeypatch.setattr(httpx2.HTTPTransport, "handle_request", forbidden)
    c = client_for(tmp_path)
    pid = c.post("/projects", headers=HEADERS, json={"name": "Site"}).json()["id"]
    _, item = contract(c, pid, "Install electrical distribution board")
    evidence = c.post(
        f"/projects/{pid}/evidence",
        headers=HEADERS,
        files={"file": ("image.png", image_bytes(), "image/png")},
    ).json()["id"]
    return c, pid, item, evidence, tmp_path


def test_match_explanation_review_and_reconnection(setup):
    c, pid, item, ev, directory = setup
    obs = add_analysis(directory, ev)
    base = f"/projects/{pid}/matches"
    assert c.post(base + "/generate", headers=HEADERS).json()["created"] == 1
    match = c.get(base, headers=HEADERS).json()[0]
    assert match["contract_item_id"] == item and match["observation_id"] == obs
    assert match["review_status"] == "pending" and match["is_current"]
    assert match["observation_provider"] == "openai"
    for support in match["supporting_observations"]:
        assert support["text"] in GROUPS[support["group"]]
        assert support["text"] in match["explanation"]
    assert "not a probability" in match["score_kind"]
    url = base + "/" + match["id"]
    for decision in ["confirm", "reopen", "reject", "reopen", "confirm"]:
        r = c.post(url + "/" + decision, headers=HEADERS)
        assert r.status_code == 200
        reviewed = r.json()
        assert (
            reviewed["review_status"]
            == {"confirm": "confirmed", "reject": "rejected", "reopen": "pending"}[decision]
        )
        assert (reviewed["reviewed_at"] is None) == (decision == "reopen")
        assert (reviewed["reviewed_by"] is None) == (decision == "reopen")
    assert c.post(url + "/reject", headers=HEADERS).status_code == 409
    assert c.post(base + "/generate", headers=HEADERS).json()["created"] == 0
    assert client_for(directory).get(url, headers=HEADERS).json() == reviewed


def test_empty_latest_analysis_prevents_old_positive(setup):
    c, pid, _, ev, directory = setup
    add_analysis(directory, ev)
    base = f"/projects/{pid}/matches"
    c.post(base + "/generate", headers=HEADERS)
    add_analysis(directory, ev, {k: [] for k in GROUPS})
    assert c.post(base + "/generate", headers=HEADERS).json()["created"] == 0
    match = c.get(base, headers=HEADERS).json()[0]
    assert not match["is_current"]
    assert c.post(base + "/" + match["id"] + "/confirm", headers=HEADERS).status_code == 409


@pytest.mark.parametrize("kwargs", [{"mock": True}, {"status": "failed"}, {"invalid": True}])
def test_mock_failed_invalid_sources_excluded(setup, kwargs):
    c, pid, _, ev, directory = setup
    add_analysis(directory, ev, **kwargs)
    assert c.post(f"/projects/{pid}/matches/generate", headers=HEADERS).json()["created"] == 0


def test_unconfirmed_and_unrelated_items_excluded(setup):
    c, pid, _, ev, directory = setup
    contract(c, pid, "Install switchboard", confirmed=False)
    contract(c, pid, "Install plumbing water pipes")
    contract(c, pid, "Construction equipment installation site works completed")
    add_analysis(directory, ev)
    c.post(f"/projects/{pid}/matches/generate", headers=HEADERS)
    assert len(c.get(f"/projects/{pid}/matches", headers=HEADERS).json()) == 1


def test_isolation_and_invalid_ids(setup):
    c, pid, _, ev, directory = setup
    add_analysis(directory, ev)
    base = f"/projects/{pid}/matches"
    c.post(base + "/generate", headers=HEADERS)
    match = c.get(base, headers=HEADERS).json()[0]
    other = c.post("/projects", headers=HEADERS, json={"name": "Other"}).json()["id"]
    contract(c, other, "Install electrical distribution board")
    otherbase = f"/projects/{other}/matches"
    assert c.post(otherbase + "/generate", headers=HEADERS).json()["created"] == 0
    assert c.get(otherbase + "/" + match["id"], headers=HEADERS).status_code == 404
    assert c.post(otherbase + "/" + match["id"] + "/confirm", headers=HEADERS).status_code == 404
    assert c.get(base + "/not-uuid", headers=HEADERS).status_code == 422
    assert c.get(base + "/" + str(uuid4()), headers=HEADERS).status_code == 404
    assert c.post(f"/projects/{uuid4()}/matches/generate", headers=HEADERS).status_code == 404
    assert c.get(base).status_code == 401
    assert (
        c.post(base + "/generate", headers={"Authorization": "Bearer invalid"}).status_code == 401
    )
    with connect(directory / "projects.sqlite3") as db:
        values = dict(db.execute("SELECT * FROM local_matches").fetchone())
        values["id"] = str(uuid4())
        values["project_id"] = other
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                f"INSERT INTO local_matches ({','.join(values)}) "
                f"VALUES ({','.join('?' for _ in values)})",
                tuple(values.values()),
            )


def test_multiple_analyses_keep_history_and_decisions(setup):
    c, pid, _, ev, directory = setup
    first = add_analysis(directory, ev)
    base = f"/projects/{pid}/matches"
    c.post(base + "/generate", headers=HEADERS)
    old = c.get(base, headers=HEADERS).json()[0]
    c.post(base + "/" + old["id"] + "/reject", headers=HEADERS)
    newest = add_analysis(directory, ev)
    assert c.post(base + "/generate", headers=HEADERS).json()["created"] == 1
    rows = c.get(base, headers=HEADERS).json()
    assert next(r for r in rows if r["observation_id"] == first)["review_status"] == "rejected"
    assert not next(r for r in rows if r["observation_id"] == first)["is_current"]
    assert next(r for r in rows if r["observation_id"] == newest)["review_status"] == "pending"
    assert c.post(base + "/generate", headers=HEADERS).json()["created"] == 0


def test_synonyms_generic_and_unrelated_terms():
    assert score_item("Install wiring", {"objects_certain": ["No wiring visible"]}) is None
    assert score_item("Install switchboard", GROUPS)
    assert score_item("Install electrical distribution panel", GROUPS)
    assert score_item("Plumbing pipework installation", GROUPS) is None
    assert score_item("Construction site equipment works installation", GROUPS) is None
    assert (
        score_item("Install equipment", {"objects_certain": ["Construction equipment at site"]})
        is None
    )
