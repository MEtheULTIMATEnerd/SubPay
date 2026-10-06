"""Data access for evidence.

SupabaseEvidenceRepository acts as the signed-in user, so Row Level Security
limits every query to their organisation's projects.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Protocol
from uuid import UUID

from app.core import errors
from app.db.supabase import DatabaseError, SupabaseRest
from app.schemas.evidence import Evidence, EvidenceType

_SEARCH_COLUMNS = ("title", "description", "code", "original_filename")

# Database check constraints -> the field and message shown to the user.
_CONSTRAINTS: dict[str, tuple[str, str]] = {
    "evidence_file_or_note_check": ("description", "Add a file or a written note"),
    "evidence_title_length": ("title", "Title must be 1 to 200 characters"),
    "evidence_description_length": ("description", "Description must be 5000 characters or fewer"),
    "evidence_metadata_is_object": ("metadata", "Metadata must be an object"),
}


@dataclass(frozen=True)
class EvidenceFilters:
    """How to narrow an evidence list. Dates are whole days in UTC, both inclusive."""

    q: str | None = None
    evidence_type: EvidenceType | None = None
    captured_from: date | None = None
    captured_to: date | None = None
    # None: active and archived. True: archived only. False: active only.
    archived: bool | None = None
    limit: int = 50
    offset: int = 0


class EvidenceRepository(Protocol):
    def project_exists(self, project_id: UUID) -> bool: ...

    def create(self, values: dict[str, Any]) -> Evidence: ...

    def list_for_project(self, project_id: UUID, filters: EvidenceFilters) -> list[Evidence]: ...

    def get(self, evidence_id: UUID) -> Evidence | None: ...

    def update(self, evidence_id: UUID, changes: dict[str, Any]) -> Evidence | None: ...


def _quoted(value: str) -> str:
    """A value inside PostgREST's and=(...) / or=(...) syntax."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _search_pattern(q: str) -> str:
    """Match the text anywhere, treating what the user typed literally."""
    literal = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace("*", "")
    return f"*{literal}*"


def _start_of_day(day: date) -> str:
    return datetime.combine(day, time.min, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_filters(project_id: UUID, filters: EvidenceFilters) -> dict[str, str]:
    params = {"project_id": f"eq.{project_id}"}
    if filters.evidence_type:
        params["evidence_type"] = f"eq.{filters.evidence_type}"
    if filters.archived is not None:
        params["archived"] = f"is.{'true' if filters.archived else 'false'}"

    bounds = []
    if filters.captured_from:
        bounds.append(f"captured_at.gte.{_quoted(_start_of_day(filters.captured_from))}")
    if filters.captured_to:
        next_day = filters.captured_to + timedelta(days=1)
        bounds.append(f"captured_at.lt.{_quoted(_start_of_day(next_day))}")
    if bounds:
        params["and"] = f"({','.join(bounds)})"

    q = (filters.q or "").strip()
    if q:
        pattern = _quoted(_search_pattern(q))
        params["or"] = (
            "(" + ",".join(f"{column}.ilike.{pattern}" for column in _SEARCH_COLUMNS) + ")"
        )
    return params


class SupabaseEvidenceRepository:
    def __init__(self, rest: SupabaseRest) -> None:
        self._rest = rest

    def project_exists(self, project_id: UUID) -> bool:
        return bool(self._rest.select("projects", {"id": f"eq.{project_id}"}, columns="id"))

    def create(self, values: dict[str, Any]) -> Evidence:
        # uploaded_by, sequence_number and code are filled in by the database.
        try:
            return Evidence.model_validate(self._rest.insert("evidence", values))
        except DatabaseError as exc:
            raise _friendly_error(exc) from exc

    def list_for_project(self, project_id: UUID, filters: EvidenceFilters) -> list[Evidence]:
        rows = self._rest.select(
            "evidence",
            build_filters(project_id, filters),
            order="captured_at.desc,id.asc",
            limit=filters.limit,
            offset=filters.offset,
        )
        return [Evidence.model_validate(row) for row in rows]

    def get(self, evidence_id: UUID) -> Evidence | None:
        rows = self._rest.select("evidence", {"id": f"eq.{evidence_id}"}, limit=1)
        return Evidence.model_validate(rows[0]) if rows else None

    def update(self, evidence_id: UUID, changes: dict[str, Any]) -> Evidence | None:
        try:
            rows = self._rest.update("evidence", {"id": f"eq.{evidence_id}"}, changes)
        except DatabaseError as exc:
            raise _friendly_error(exc) from exc
        return Evidence.model_validate(rows[0]) if rows else None


def _friendly_error(exc: DatabaseError) -> Exception:
    for constraint, (field, message) in _CONSTRAINTS.items():
        if constraint in exc.pg_message:
            return errors.validation_error(message, field=field)
    return exc
