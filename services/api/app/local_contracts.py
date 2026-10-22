"""Local contract storage and review, isolated from Supabase workflows."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import FileResponse

from app.document_text import draft_items, extract

MAX_UPLOAD = 20 * 1024 * 1024
TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class ItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    item_code: str = Field(default="", max_length=50)
    description: str = Field(min_length=3, max_length=2000)
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=50)
    rate: float | None = Field(default=None, ge=0)
    amount: float | None = Field(default=None, ge=0)


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["confirmed", "rejected", "draft"]


def now():
    return datetime.now(timezone.utc).isoformat()


def schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS local_contracts (
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
        original_filename TEXT NOT NULL, mime_type TEXT NOT NULL, storage_path TEXT NOT NULL,
        size_bytes INTEGER NOT NULL, extracted_text TEXT NOT NULL, sources TEXT NOT NULL,
        limitation TEXT, created_at TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS local_contract_items (
        id TEXT PRIMARY KEY, contract_id TEXT NOT NULL REFERENCES local_contracts(id),
        item_code TEXT NOT NULL, description TEXT NOT NULL, quantity REAL, unit TEXT,
        rate REAL, amount REAL, source_reference TEXT NOT NULL, extracted_description TEXT,
        origin TEXT NOT NULL CHECK(origin IN ('extracted','manual')),
        review_status TEXT NOT NULL CHECK(review_status IN ('draft','confirmed','rejected')),
        reviewed_by TEXT, reviewed_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")


def require_project(db, project_id):
    if not db.execute("SELECT id FROM projects WHERE id=?", (str(project_id),)).fetchone():
        raise HTTPException(404, "Project not found")


def require_contract(db, project_id, contract_id):
    row = db.execute(
        "SELECT * FROM local_contracts WHERE id=? AND project_id=?",
        (str(contract_id), str(project_id)),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Contract not found in project")
    return dict(row)


def add_item(db, contract_id, body, source, origin):
    stamp = now()
    record = {
        **ItemInput(**body).model_dump(),
        "id": str(uuid4()),
        "contract_id": str(contract_id),
        "source_reference": source,
        "origin": origin,
        "extracted_description": body["description"] if origin == "extracted" else None,
        "review_status": "draft",
        "reviewed_by": None,
        "reviewed_at": None,
        "created_at": stamp,
        "updated_at": stamp,
    }
    columns = ",".join(record)
    db.execute(
        f"INSERT INTO local_contract_items ({columns}) VALUES ({','.join('?' for _ in record)})",
        tuple(record.values()),
    )
    return record


def register_contract_routes(app: FastAPI, data_dir: Path, connect):
    database = data_dir / "projects.sqlite3"
    base = "/projects/{project_id}/contracts"

    @app.post(base, status_code=201)
    def upload(project_id: UUID, file: UploadFile):
        saved = None
        try:
            extension = Path((file.filename or "").replace("\\", "/")).suffix.lower()
            if extension not in TYPES or file.content_type != TYPES[extension]:
                raise HTTPException(415, "Matching PDF/DOCX extension and MIME type required")
            with connect(database) as db:
                require_project(db, project_id)
            data = file.file.read(MAX_UPLOAD + 1)
            if len(data) > MAX_UPLOAD:
                raise HTTPException(413, "Contract must be 20 MB or smaller")
            try:
                sources = extract(data, extension)
                drafts = draft_items(sources)
            except Exception as exc:
                raise HTTPException(
                    422, "Document cannot be parsed or exceeds extraction limits"
                ) from exc
            text = "\n".join(s["text"] for s in sources)
            limitation = (
                None
                if drafts
                else (
                    "No readable text; scanned PDFs require OCR. Manual entry is available."
                    if not text.strip()
                    else "No reliable numbered items found. Review text and enter items manually."
                )
            )
            contract_id = str(uuid4())
            folder = data_dir / "uploads" / "contracts"
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            destination = folder / f"{contract_id}{extension}"
            with destination.open("xb") as output:
                saved = destination
                output.write(data)
            record = {
                "id": contract_id,
                "project_id": str(project_id),
                "original_filename": (file.filename or "contract")
                .replace("\\", "/")
                .split("/")[-1][:255],
                "mime_type": file.content_type,
                "storage_path": str(destination.relative_to(data_dir)),
                "size_bytes": len(data),
                "extracted_text": text,
                "sources": json.dumps(sources),
                "limitation": limitation,
                "created_at": now(),
            }
            with connect(database) as db:
                schema(db)
                require_project(db, project_id)
                db.execute(
                    f"INSERT INTO local_contracts ({','.join(record)}) "
                    f"VALUES ({','.join('?' for _ in record)})",
                    tuple(record.values()),
                )
                for item in drafts:
                    source = item.pop("source_reference")
                    add_item(db, contract_id, item, source, "extracted")
            return {**record, "sources": sources, "draft_item_count": len(drafts)}
        except BaseException:
            if saved is not None:
                saved.unlink(missing_ok=True)
            raise
        finally:
            file.file.close()

    @app.get(base)
    def list_contracts(project_id: UUID):
        with connect(database) as db:
            schema(db)
            require_project(db, project_id)
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM local_contracts WHERE project_id=? ORDER BY created_at,id",
                    (str(project_id),),
                )
            ]

    @app.get(base + "/{contract_id}")
    def get_contract(project_id: UUID, contract_id: UUID):
        with connect(database) as db:
            schema(db)
            record = require_contract(db, project_id, contract_id)
            record["sources"] = json.loads(record["sources"])
            return record

    @app.get(base + "/{contract_id}/original")
    def original(project_id: UUID, contract_id: UUID):
        with connect(database) as db:
            schema(db)
            record = require_contract(db, project_id, contract_id)
        path = (data_dir / record["storage_path"]).resolve()
        if not path.is_relative_to(data_dir.resolve()) or not path.is_file():
            raise HTTPException(404, "Original document unavailable")
        return FileResponse(
            path, media_type=record["mime_type"], filename=record["original_filename"]
        )

    @app.get(base + "/{contract_id}/items")
    def items(project_id: UUID, contract_id: UUID):
        with connect(database) as db:
            schema(db)
            require_contract(db, project_id, contract_id)
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM local_contract_items WHERE contract_id=? ORDER BY created_at,id",
                    (str(contract_id),),
                )
            ]

    @app.post(base + "/{contract_id}/items", status_code=201)
    def manual_item(project_id: UUID, contract_id: UUID, body: ItemInput):
        with connect(database) as db:
            schema(db)
            require_contract(db, project_id, contract_id)
            return add_item(
                db, contract_id, body.model_dump(), "Manual entry; not extracted", "manual"
            )

    def require_item(db, project_id, contract_id, item_id):
        schema(db)
        require_contract(db, project_id, contract_id)
        row = db.execute(
            "SELECT * FROM local_contract_items WHERE id=? AND contract_id=?",
            (str(item_id), str(contract_id)),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Contract item not found")
        return dict(row)

    @app.patch(base + "/{contract_id}/items/{item_id}")
    def edit_item(project_id: UUID, contract_id: UUID, item_id: UUID, body: ItemInput):
        with connect(database) as db:
            record = require_item(db, project_id, contract_id, item_id)
            if record["review_status"] != "draft":
                raise HTTPException(409, "Reopen item to draft before editing")
            values = body.model_dump(exclude_unset=True)
            values["updated_at"] = now()
            db.execute(
                f"UPDATE local_contract_items SET {','.join(k + '=?' for k in values)} WHERE id=?",
                (*values.values(), str(item_id)),
            )
            return dict(
                db.execute(
                    "SELECT * FROM local_contract_items WHERE id=?", (str(item_id),)
                ).fetchone()
            )

    @app.post(base + "/{contract_id}/items/{item_id}/review")
    def review(project_id: UUID, contract_id: UUID, item_id: UUID, body: ReviewInput):
        with connect(database) as db:
            require_item(db, project_id, contract_id, item_id)
            stamp = now()
            db.execute(
                "UPDATE local_contract_items SET review_status=?,reviewed_by=?,reviewed_at=?,"
                "updated_at=? WHERE id=?",
                (
                    body.status,
                    None if body.status == "draft" else "local-development-user",
                    None if body.status == "draft" else stamp,
                    stamp,
                    str(item_id),
                ),
            )
            return dict(
                db.execute(
                    "SELECT * FROM local_contract_items WHERE id=?", (str(item_id),)
                ).fetchone()
            )
