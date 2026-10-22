"""Explainable lexical relevance over real persisted observations, not completion."""

import json
import re
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException

from app.ai.evidence import EvidenceUnderstandingResult
from app.local_contracts import now, require_project
from app.local_contracts import schema as contract_schema
from app.local_evidence import schema as evidence_schema
from app.local_vision import Observations

METHOD = "construction-lexical-v1"
STOP = set(
    "a an the and or to of for from in on at with by is are be as per "
    "install installed installation installing work works construction equipment "
    "complete completed completion site supply provide providing visible object "
    "objects activity activities certain possible connected".split()
)
DOMAIN = {"electrical", "structural", "building"}
ALIASES = [
    (
        r"\b(?:distribution\s+(?:board|panel)|switchboards?|panelboards?|consumer\s+units?)\b",
        "distributionboard",
    ),
    (r"\b(?:circuit\s+breakers?|rcds?|protective\s+devices?)\b", "breaker"),
    (r"\b(?:wires?|wiring|cables?|cabling)\b", "wire"),
    (r"\b(?:pipes?|pipework|plumbing)\b", "pipe"),
    (r"\b(?:rebar|reinforcement|reinforcing\s+(?:steel|mesh))\b", "reinforcement"),
]


def terms(text):
    text = text.lower()
    for pattern, replacement in ALIASES:
        text = re.sub(pattern, replacement, text)
    return {t for t in re.findall(r"[a-z]+", text) if len(t) > 2 and t not in STOP}


def score_item(description, observations):
    wanted = terms(description)
    supporting = []
    hits = set()
    for group, labels in observations.items():
        for label in labels:
            if re.search(r"\b(no|not|without|absent|missing)\b", label, re.IGNORECASE):
                continue
            overlap = wanted & terms(label)
            if overlap - DOMAIN:
                hits |= overlap
                supporting.append({"group": group, "text": label})
    score = round(len(hits) / len(wanted), 4) if wanted else 0
    if score < 0.34 or not hits - DOMAIN:
        return None
    return {"score": score, "supporting_observations": supporting, "matched_terms": sorted(hits)}


def schema(db):
    contract_schema(db)
    evidence_schema(db)
    db.execute("""CREATE TABLE IF NOT EXISTS local_matches (
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
        contract_item_id TEXT NOT NULL REFERENCES local_contract_items(id),
        evidence_id TEXT NOT NULL REFERENCES local_evidence(id),
        observation_id TEXT NOT NULL REFERENCES local_observations(id),
        score REAL NOT NULL CHECK(score>0 AND score<=1), explanation TEXT NOT NULL,
        method TEXT NOT NULL, supporting_observations TEXT NOT NULL,
        observation_provider TEXT NOT NULL, observation_model TEXT NOT NULL,
        item_description TEXT NOT NULL,
        review_status TEXT NOT NULL CHECK(review_status IN ('pending','confirmed','rejected')),
        reviewed_by TEXT, reviewed_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(contract_item_id,evidence_id,observation_id),
        CHECK((review_status='pending' AND reviewed_by IS NULL AND reviewed_at IS NULL)
          OR (review_status<>'pending' AND reviewed_by IS NOT NULL
              AND reviewed_at IS NOT NULL)))""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS local_matches_project_guard
        BEFORE INSERT ON local_matches BEGIN
        SELECT CASE WHEN NOT EXISTS (
          SELECT 1 FROM local_contract_items i JOIN local_contracts c ON c.id=i.contract_id
          JOIN local_evidence e ON e.id=NEW.evidence_id
          JOIN local_observations o ON o.id=NEW.observation_id AND o.evidence_id=e.id
          WHERE i.id=NEW.contract_item_id AND c.project_id=NEW.project_id
          AND e.project_id=NEW.project_id AND i.review_status='confirmed'
          AND o.status='ready' AND o.provider='openai'
        ) THEN RAISE(ABORT,'Invalid match project or source') END; END""")


def eligible_observation(db, evidence):
    # Newest attempt wins, even if empty/mock/failed: never resurrect older positives.
    row = db.execute(
        "SELECT * FROM local_observations WHERE evidence_id=? ORDER BY rowid DESC LIMIT 1",
        (evidence["id"],),
    ).fetchone()
    if not row or evidence["processing_status"] != "ready" or row["status"] != "ready":
        return None
    if row["provider"] != "openai" or not row["model"] or not row["processed_at"]:
        return None
    try:
        data = json.loads(row["structured_data"])
        if data.get("mock") is not False:
            return None
        observation = Observations.model_validate(data["observations"])
        understanding = EvidenceUnderstandingResult.model_validate(data["understanding"])
        if str(understanding.evidence_id) != evidence["id"]:
            return None
        flags = understanding.signals.other_signals
        if flags.get("mock") is not False or flags.get("not_real_vision") is not False:
            return None
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
    return dict(row), observation.model_dump()


def current(db, match):
    item = db.execute(
        "SELECT description,review_status FROM local_contract_items WHERE id=?",
        (match["contract_item_id"],),
    ).fetchone()
    evidence = db.execute(
        "SELECT * FROM local_evidence WHERE id=?", (match["evidence_id"],)
    ).fetchone()
    eligible = eligible_observation(db, evidence) if evidence else None
    return bool(
        item
        and item["review_status"] == "confirmed"
        and item["description"] == match["item_description"]
        and eligible
        and eligible[0]["id"] == match["observation_id"]
    )


def present(db, row):
    record = dict(row)
    record["supporting_observations"] = json.loads(record["supporting_observations"])
    record["is_current"] = current(db, record)
    record["score_kind"] = "lexical relevance heuristic; not a probability or completion assessment"
    return record


def generate(db, project_id):
    require_project(db, project_id)
    items = db.execute(
        "SELECT i.* FROM local_contract_items i JOIN local_contracts c "
        "ON c.id=i.contract_id WHERE c.project_id=? AND i.review_status='confirmed' ORDER BY i.id",
        (str(project_id),),
    ).fetchall()
    evidence = db.execute(
        "SELECT * FROM local_evidence WHERE project_id=? ORDER BY id", (str(project_id),)
    ).fetchall()
    created = 0
    for ev in evidence:
        result = eligible_observation(db, ev)
        if result is None:
            continue
        observation, groups = result
        for item in items:
            candidate = score_item(item["description"], groups)
            if candidate is None:
                continue
            stamp = now()
            explanation = (
                "Shared specific terms: " + ", ".join(candidate["matched_terms"]) + ". "
                "Stored observations: "
                + json.dumps(candidate["supporting_observations"])
                + ". Object relevance only; does not establish completion or compliance."
            )
            record = {
                "id": str(uuid4()),
                "project_id": str(project_id),
                "contract_item_id": item["id"],
                "evidence_id": ev["id"],
                "observation_id": observation["id"],
                "score": candidate["score"],
                "explanation": explanation,
                "method": METHOD,
                "supporting_observations": json.dumps(candidate["supporting_observations"]),
                "observation_provider": observation["provider"],
                "observation_model": observation["model"],
                "item_description": item["description"],
                "review_status": "pending",
                "reviewed_by": None,
                "reviewed_at": None,
                "created_at": stamp,
                "updated_at": stamp,
            }
            row = db.execute(
                f"INSERT INTO local_matches ({','.join(record)}) VALUES "
                f"({','.join('?' for _ in record)}) "
                "ON CONFLICT(contract_item_id,evidence_id,observation_id) DO NOTHING",
                tuple(record.values()),
            )
            created += row.rowcount
    return {"created": created, "method": METHOD}


def register_matching_routes(app: FastAPI, data_dir: Path, connect):
    path = data_dir / "projects.sqlite3"
    base = "/projects/{project_id}/matches"

    @app.post(base + "/generate")
    def generate_matches(project_id: UUID):
        with connect(path) as db:
            schema(db)
            db.execute("BEGIN IMMEDIATE")
            return generate(db, project_id)

    @app.get(base)
    def list_matches(project_id: UUID):
        with connect(path) as db:
            schema(db)
            require_project(db, project_id)
            return [
                present(db, r)
                for r in db.execute(
                    "SELECT * FROM local_matches WHERE project_id=? ORDER BY created_at,id",
                    (str(project_id),),
                )
            ]

    def require_match(db, project_id, match_id):
        schema(db)
        row = db.execute(
            "SELECT * FROM local_matches WHERE id=? AND project_id=?",
            (str(match_id), str(project_id)),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Match not found in project")
        return row

    @app.get(base + "/{match_id}")
    def get_match(project_id: UUID, match_id: UUID):
        with connect(path) as db:
            return present(db, require_match(db, project_id, match_id))

    def review(project_id, match_id, status):
        with connect(path) as db:
            schema(db)
            db.execute("BEGIN IMMEDIATE")
            record = require_match(db, project_id, match_id)
            old = record["review_status"]
            if old == status:
                return present(db, record)
            if old != "pending" and status != "pending":
                raise HTTPException(409, "Reopen the match before changing the decision")
            if status == "confirmed" and not current(db, record):
                raise HTTPException(409, "Match source is stale; generate current suggestions")
            stamp = now()
            db.execute(
                "UPDATE local_matches SET review_status=?,reviewed_by=?,reviewed_at=?,"
                "updated_at=? WHERE id=?",
                (
                    status,
                    None if status == "pending" else "local-development-user",
                    None if status == "pending" else stamp,
                    stamp,
                    str(match_id),
                ),
            )
            return present(db, require_match(db, project_id, match_id))

    @app.post(base + "/{match_id}/confirm")
    def confirm(project_id: UUID, match_id: UUID):
        return review(project_id, match_id, "confirmed")

    @app.post(base + "/{match_id}/reject")
    def reject(project_id: UUID, match_id: UUID):
        return review(project_id, match_id, "rejected")

    @app.post(base + "/{match_id}/reopen")
    def reopen(project_id: UUID, match_id: UUID):
        return review(project_id, match_id, "pending")
