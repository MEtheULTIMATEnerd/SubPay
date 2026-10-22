"""Opt-in, single-user localhost projects. Not production authentication."""

import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from ipaddress import ip_address
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.responses import JSONResponse

DATA_DIR = Path(__file__).resolve().parents[1] / ".local-data"


class LocalSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SUBPAY_LOCAL_", extra="ignore")
    enabled: bool = False
    access_token: SecretStr = SecretStr("")
    data_dir: Path = DATA_DIR
    origins: list[str] = ["http://localhost:3101", "http://127.0.0.1:3101"]
    vision_provider: str = "mock"
    vision_model: str = "gpt-4o-mini"


class ProjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)

    @field_validator("name", "description")
    @classmethod
    def no_control_characters(cls, value: str) -> str:
        if any(ord(c) < 32 and c not in "\n\t" for c in value):
            raise ValueError("Unsupported control character")
        return value


class Project(ProjectInput):
    id: UUID
    created_at: datetime
    updated_at: datetime


@contextmanager
def connect(path: Path):
    # One connection per operation: no cross-thread shared connections.
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("""CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY NOT NULL,
            name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 200),
            description TEXT NOT NULL DEFAULT '' CHECK(length(description) <= 5000),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        with db:
            yield db
    finally:
        db.close()


def create_local_app(settings: LocalSettings) -> FastAPI:
    if not settings.enabled:
        raise ValueError("Local integration must be explicitly enabled")
    token = settings.access_token.get_secret_value()
    if len(token) < 32 or not token.isascii() or token != token.strip():
        raise ValueError("SUBPAY_LOCAL_ACCESS_TOKEN must be at least 32 ASCII characters")
    allowed = {"http://localhost:3101", "http://127.0.0.1:3101"}
    if not settings.origins or not set(settings.origins).issubset(allowed):
        raise ValueError("Local integration origins must be approved loopback origins")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    path = settings.data_dir / "projects.sqlite3"
    app.state.local_settings = settings

    @app.middleware("http")
    async def local_access(request: Request, call_next):
        try:
            loopback = bool(request.client and ip_address(request.client.host).is_loopback)
        except ValueError:
            loopback = False
        if not loopback:
            return JSONResponse({"detail": "Loopback access only"}, status_code=403)
        if (
            request.headers.get("origin") is not None
            and request.headers["origin"] not in settings.origins
        ):
            return JSONResponse({"detail": "Origin not permitted"}, status_code=403)
        scheme, _, supplied = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(
            supplied.encode(), token.encode()
        ):
            return JSONResponse(
                {"detail": "Local access token required"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)

    @app.post("/projects", response_model=Project, status_code=201)
    def create_project(body: ProjectInput):
        now = datetime.now(timezone.utc).isoformat()
        record = {**body.model_dump(), "id": str(uuid4()), "created_at": now, "updated_at": now}
        with connect(path) as db:
            db.execute(
                "INSERT INTO projects (id,name,description,created_at,updated_at) "
                "VALUES (:id,:name,:description,:created_at,:updated_at)",
                record,
            )
        return record

    @app.get("/projects", response_model=list[Project])
    def list_projects():
        with connect(path) as db:
            return [
                dict(row) for row in db.execute("SELECT * FROM projects ORDER BY created_at, id")
            ]

    @app.get("/projects/{project_id}", response_model=Project)
    def get_project(project_id: UUID):
        with connect(path) as db:
            row = db.execute("SELECT * FROM projects WHERE id = ?", (str(project_id),)).fetchone()
        if row is None:
            raise HTTPException(404, "Project not found")
        return dict(row)

    from app.local_contracts import register_contract_routes
    from app.local_evidence import register_evidence_routes
    from app.local_matching import register_matching_routes
    from app.local_packages import register_package_routes

    register_contract_routes(app, settings.data_dir, connect)
    register_evidence_routes(app, settings.data_dir, connect, settings.vision_provider)
    register_matching_routes(app, settings.data_dir, connect)
    register_package_routes(app, settings.data_dir)
    return app
