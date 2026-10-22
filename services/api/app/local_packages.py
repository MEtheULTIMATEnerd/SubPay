"""Read-only draft exports over one SQLite snapshot; no certification or AI calls."""

import json
import sqlite3
from contextlib import closing
from html import escape
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from starlette.responses import HTMLResponse, JSONResponse

from app.local_contracts import now, require_project
from app.local_matching import current, eligible_observation

VERSION = "subpay.draft-claim-support.v1"
LIMITATIONS = [
    "This is a draft evidence-support package, not an invoice or certified claim.",
    "AI observations are not proof of completion.",
    "Matching scores are lexical heuristics, not probabilities.",
    "Human confirmation is not independent contractual certification.",
    "Quantities, quality, compliance and payment entitlement are not established "
    "unless independently verified.",
    "SubPay does not certify or submit claims. Original files are not embedded.",
]


def select(record, fields):
    return {key: record[key] for key in fields.split()}


def rows(db, table, query, params):
    exists = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return db.execute(query, params).fetchall() if exists else []


def build_package(db, project_id):
    """Caller holds a read transaction, including all eligibility lookups."""
    require_project(db, project_id)
    pid = str(project_id)
    project = dict(db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone())
    contracts = rows(
        db,
        "local_contracts",
        "SELECT * FROM local_contracts WHERE project_id=? ORDER BY id",
        (pid,),
    )
    items = rows(
        db,
        "local_contract_items",
        "SELECT i.* FROM local_contract_items i JOIN local_contracts c ON c.id=i.contract_id "
        "WHERE c.project_id=? AND i.review_status='confirmed' ORDER BY i.contract_id,i.id",
        (pid,),
    )
    evidence = rows(
        db,
        "local_evidence",
        "SELECT * FROM local_evidence WHERE project_id=? ORDER BY id",
        (pid,),
    )
    evidence_by_id = {e["id"]: e for e in evidence}
    items_by_id = {i["id"]: i for i in items}
    links = {i["id"]: [] for i in items}
    linked = set()
    matches = rows(
        db,
        "local_matches",
        "SELECT * FROM local_matches WHERE project_id=? AND review_status='confirmed' "
        "ORDER BY created_at,id",
        (pid,),
    )
    for match in matches:
        ev = evidence_by_id.get(match["evidence_id"])
        if (
            match["contract_item_id"] not in items_by_id
            or ev is None
            or not match["reviewed_by"]
            or not match["reviewed_at"]
        ):
            continue
        if not current(db, match):
            continue
        analysis, observations = eligible_observation(db, ev)
        if analysis["evidence_id"] != ev["id"]:
            continue
        # Persisted schema-valid empty observations never establish support.
        if not any(observations.values()):
            continue
        links[match["contract_item_id"]].append(
            {
                "evidence": select(ev, "id original_filename content_type size uploaded_at"),
                "analysis": {
                    **select(analysis, "id provider model processed_at"),
                    "mock": False,
                    "observations": observations,
                },
                "match": {
                    **select(
                        match,
                        "id score explanation method review_status reviewed_by "
                        "reviewed_at created_at updated_at",
                    ),
                    "score_kind": "lexical relevance heuristic; not a probability",
                    "supporting_observations": json.loads(match["supporting_observations"]),
                },
            }
        )
        linked.add(ev["id"])
    exported_items = [
        {
            **select(
                i,
                "id contract_id item_code description quantity unit rate amount "
                "source_reference origin review_status reviewed_by reviewed_at "
                "created_at updated_at",
            ),
            "supporting_evidence": links[i["id"]],
        }
        for i in items
    ]
    missing = [i["id"] for i in items if not links[i["id"]]]
    return {
        "schema_version": VERSION,
        "package_id": str(uuid4()),
        "generated_at": now(),
        "status": "draft",
        "project": project,
        "contracts": [
            select(c, "id project_id original_filename mime_type size_bytes limitation created_at")
            for c in contracts
        ],
        "contract_items": exported_items,
        "coverage": {
            "total_confirmed_items": len(items),
            "supported_items": len(items) - len(missing),
            "unsupported_items": len(missing),
            "unsupported_item_ids": missing,
            "unlinked_evidence_count": len(evidence_by_id.keys() - linked),
            "unlinked_evidence_ids": sorted(evidence_by_id.keys() - linked),
        },
        "limitations": LIMITATIONS,
    }


def render_html(package):
    def e(value):
        return escape(str(value), quote=True)

    sections = []
    for item in package["contract_items"]:
        support = []
        for link in item["supporting_evidence"]:
            ev, analysis, match = link["evidence"], link["analysis"], link["match"]
            support.append(
                f"<h3>{e(ev['original_filename'])}</h3>"
                f"<p>Evidence {e(ev['id'])}; uploaded {e(ev['uploaded_at'])}</p>"
                f"<p>Analysis {e(analysis['id'])}: {e(analysis['provider'])} / "
                f"{e(analysis['model'])}; processed {e(analysis['processed_at'])}</p>"
                f"<pre>{e(json.dumps(analysis['observations'], indent=2))}</pre>"
                f"<p>{e(match['explanation'])}</p>"
                f"<p>Score {e(match['score'])}: {e(match['score_kind'])}; "
                f"method {e(match['method'])}</p>"
                f"<p>Human-confirmed by {e(match['reviewed_by'])} "
                f"at {e(match['reviewed_at'])}</p>"
            )
        recorded = "; ".join(
            f"{key}: {item[key]}"
            for key in ("quantity", "unit", "rate", "amount")
            if item[key] is not None
        )
        sections.append(
            f"<section><h2>{e(item['item_code'])} {e(item['description'])}</h2>"
            f"<p>Item {e(item['id'])}; contract {e(item['contract_id'])}</p>"
            f"<p>Source: {e(item['source_reference'])}. {e(recorded)}</p>"
            + ("".join(support) or "<p>No eligible confirmed supporting evidence.</p>")
            + "</section>"
        )
    coverage = package["coverage"]
    missing = "".join(
        f"<li>{e(i['description'])} ({e(i['id'])})</li>"
        for i in package["contract_items"]
        if not i["supporting_evidence"]
    )
    contracts = "".join(
        f"<li>{e(c['original_filename'])} ({e(c['id'])}); "
        f"uploaded {e(c['created_at'])}; {e(c['limitation'] or '')}</li>"
        for c in package["contracts"]
    )
    disclaimers = "".join(f"<li>{e(v)}</li>" for v in package["limitations"])
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>SubPay draft evidence-support package</title><style>"
        "body{font:16px/1.5 system-ui,sans-serif;color:#202522;max-width:960px;"
        "margin:32px auto;padding:0 24px}h1{font-size:28px}h2{font-size:21px}"
        "section{border-top:1px solid #aaa;padding:16px 0}pre{white-space:pre-wrap}"
        "p,li,pre,h1,h2,h3{overflow-wrap:anywhere}aside{border-left:4px solid #856600;"
        "padding-left:16px}@media print{body{margin:0;max-width:none;font-size:11pt}"
        "h2,h3{break-after:avoid}aside{border-color:#333}}</style></head><body>"
        f"<h1>{e(package['project']['name'])}</h1><p><strong>DRAFT evidence-support "
        f"package</strong></p><p>Project {e(package['project']['id'])}<br>"
        f"Package {e(package['package_id'])}; generated {e(package['generated_at'])}<br>"
        f"Schema {e(package['schema_version'])}</p><aside><h2>Limitations</h2>"
        f"<ul>{disclaimers}</ul></aside><h2>Coverage summary</h2>"
        f"<p>{coverage['total_confirmed_items']} confirmed items; "
        f"{coverage['supported_items']} supported; {coverage['unsupported_items']} "
        f"without eligible support; {coverage['unlinked_evidence_count']} unlinked "
        f"evidence records.</p><h2>Contracts</h2><ul>{contracts}</ul>"
        + "".join(sections)
        + f"<h2>Missing evidence</h2><ul>{missing or '<li>None.</li>'}</ul>"
        + "</body></html>"
    )


def register_package_routes(app: FastAPI, data_dir: Path):
    path = data_dir / "projects.sqlite3"

    def snapshot(project_id):
        if not path.is_file():
            raise HTTPException(404, "Project not found")
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            return build_package(db, project_id)

    def headers(project_id, extension):
        return {
            "Content-Disposition": f'attachment; filename="subpay-{project_id}-draft.{extension}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        }

    @app.get("/projects/{project_id}/claim-package.json")
    def export_json(project_id: UUID):
        return JSONResponse(snapshot(project_id), headers=headers(project_id, "json"))

    @app.get("/projects/{project_id}/claim-package.html")
    def export_html(project_id: UUID):
        return HTMLResponse(render_html(snapshot(project_id)), headers=headers(project_id, "html"))
