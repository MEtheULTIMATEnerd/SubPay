"""Private image storage and durable analysis attempts with provider provenance."""

import json
import warnings
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from PIL import Image

from app.local_contracts import now, require_project
from app.local_vision import analyse, get_local_vision

MAX_IMAGE = 10 * 1024 * 1024
MAX_PIXELS = 20_000_000
FORMATS = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"),
}


def validate_image(data: bytes):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if image.format not in FORMATS:
                    raise ValueError("Unsupported format")
                if image.width * image.height > MAX_PIXELS or getattr(image, "n_frames", 1) != 1:
                    raise ValueError("Image dimensions or frame count exceed limits")
                result = FORMATS[image.format]
                image.verify()
            with Image.open(BytesIO(data)) as image:
                image.load()
        return result
    except Exception as exc:
        raise HTTPException(422, "Invalid, unsupported or oversized image") from exc


def schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS local_evidence (
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
        original_filename TEXT NOT NULL, stored_filename TEXT NOT NULL,
        content_type TEXT NOT NULL, size INTEGER NOT NULL CHECK(size>0),
        uploaded_at TEXT NOT NULL, processing_status TEXT NOT NULL
        CHECK(processing_status IN ('uploaded','processing','ready','failed')))""")
    db.execute("""CREATE TABLE IF NOT EXISTS local_observations (
        id TEXT PRIMARY KEY, evidence_id TEXT NOT NULL REFERENCES local_evidence(id),
        provider TEXT NOT NULL, model TEXT NOT NULL, structured_data TEXT,
        processed_at TEXT, error TEXT, status TEXT NOT NULL
        CHECK(status IN ('processing','ready','failed')))""")


def require_evidence(db, project_id, evidence_id):
    row = db.execute(
        "SELECT * FROM local_evidence WHERE id=? AND project_id=?",
        (str(evidence_id), str(project_id)),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Evidence not found in project")
    return dict(row)


def register_evidence_routes(app: FastAPI, data_dir: Path, connect, provider_name: str):
    if provider_name not in {"mock", "openai"}:
        raise ValueError("Unsupported local vision provider; no fallback")
    database = data_dir / "projects.sqlite3"
    base = "/projects/{project_id}/evidence"

    @app.post(base, status_code=201)
    def upload(project_id: UUID, file: UploadFile):
        saved = None
        try:
            with connect(database) as db:
                require_project(db, project_id)
            data = file.file.read(MAX_IMAGE + 1)
            if len(data) > MAX_IMAGE:
                raise HTTPException(413, "Evidence image must be 10 MiB or smaller")
            mime, extension = validate_image(data)
            if file.content_type != mime:
                raise HTTPException(415, "Declared MIME type does not match actual image")
            evidence_id = str(uuid4())
            folder = data_dir / "uploads" / "evidence"
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            destination = folder / f"{evidence_id}{extension}"
            with destination.open("xb") as output:
                saved = destination
                output.write(data)
            record = {
                "id": evidence_id,
                "project_id": str(project_id),
                "original_filename": (file.filename or "image")
                .replace("\\", "/")
                .split("/")[-1][:255],
                "stored_filename": str(destination.relative_to(data_dir)),
                "content_type": mime,
                "size": len(data),
                "uploaded_at": now(),
                "processing_status": "uploaded",
            }
            with connect(database) as db:
                schema(db)
                require_project(db, project_id)
                db.execute(
                    f"INSERT INTO local_evidence ({','.join(record)}) "
                    f"VALUES ({','.join('?' for _ in record)})",
                    tuple(record.values()),
                )
            return record
        except BaseException:
            if saved:
                saved.unlink(missing_ok=True)
            raise
        finally:
            file.file.close()

    @app.get(base)
    def list_evidence(project_id: UUID):
        with connect(database) as db:
            schema(db)
            require_project(db, project_id)
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM local_evidence WHERE project_id=? ORDER BY uploaded_at,id",
                    (str(project_id),),
                )
            ]

    @app.get(base + "/{evidence_id}")
    def get_evidence(project_id: UUID, evidence_id: UUID):
        with connect(database) as db:
            schema(db)
            return require_evidence(db, project_id, evidence_id)

    @app.get(base + "/{evidence_id}/observations")
    def observations(project_id: UUID, evidence_id: UUID):
        with connect(database) as db:
            schema(db)
            require_evidence(db, project_id, evidence_id)
            rows = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM local_observations WHERE evidence_id=? ORDER BY rowid",
                    (str(evidence_id),),
                )
            ]
        for row in rows:
            row["structured_data"] = (
                json.loads(row["structured_data"]) if row["structured_data"] else None
            )
        return rows

    @app.post(base + "/{evidence_id}/analyse")
    def process(project_id: UUID, evidence_id: UUID, provider=Depends(get_local_vision)):
        attempt_id = str(uuid4())
        provenance = getattr(provider, "provider_name", "mock")
        model = getattr(provider, "model", "local-mock-v1")
        with connect(database) as db:
            schema(db)
            evidence = require_evidence(db, project_id, evidence_id)
            claimed = db.execute(
                "UPDATE local_evidence SET processing_status='processing' "
                "WHERE id=? AND processing_status<>'processing'",
                (str(evidence_id),),
            )
            if claimed.rowcount != 1:
                raise HTTPException(409, "Analysis already processing")
            db.execute(
                "INSERT INTO local_observations (id,evidence_id,provider,model,status) "
                "VALUES (?,?,?,?,'processing')",
                (attempt_id, str(evidence_id), provenance, model),
            )
        # File decoding and inference happen outside the SQLite transaction.
        try:
            path = (data_dir / evidence["stored_filename"]).resolve()
            if not path.is_relative_to(data_dir.resolve()):
                raise ValueError("Invalid storage path")
            with path.open("rb") as image:
                data = image.read(MAX_IMAGE + 1)
            if len(data) > MAX_IMAGE:
                raise ValueError("Stored image exceeds limit")
            mime, _ = validate_image(data)
            if mime != evidence["content_type"]:
                raise ValueError("Stored image type changed")
            result = analyse(provider, evidence_id, data, mime)
        except Exception:
            # Never persist or return arbitrary provider exception text (may contain secrets).
            with connect(database) as db:
                db.execute(
                    "UPDATE local_observations SET status='failed',processed_at=?,error=? "
                    "WHERE id=?",
                    (now(), "Analysis failed; no fallback used", attempt_id),
                )
                db.execute(
                    "UPDATE local_evidence SET processing_status='failed' WHERE id=?",
                    (str(evidence_id),),
                )
            raise HTTPException(502, "Analysis failed; no fallback used") from None
        with connect(database) as db:
            db.execute(
                "UPDATE local_observations SET status='ready',processed_at=?,structured_data=? "
                "WHERE id=?",
                (now(), json.dumps(result), attempt_id),
            )
            db.execute(
                "UPDATE local_evidence SET processing_status='ready' WHERE id=?",
                (str(evidence_id),),
            )
        return {
            "evidence_id": str(evidence_id),
            "attempt_id": attempt_id,
            "status": "ready",
            "provider": provenance,
            "model": model,
            **result,
        }
