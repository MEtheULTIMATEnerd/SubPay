"""Evidence capture and upload (F06) and the evidence library (F07).

Evidence in another organisation is indistinguishable from evidence that does
not exist: both are a 404.
"""

import json
from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, File, Form, Query, UploadFile, status
from pydantic import AwareDatetime

from app.api.deps import EvidenceLibrary
from app.core import errors
from app.repositories.evidence import EvidenceFilters
from app.schemas.evidence import (
    Evidence,
    EvidenceDetail,
    EvidenceList,
    EvidenceType,
    EvidenceUpdate,
    check_metadata,
)
from app.services import uploads
from app.services.evidence import MAX_EVIDENCE_BYTES

router = APIRouter(tags=["evidence"])


def _parse_metadata(raw: str | None) -> dict[str, Any]:
    if raw is None or not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise errors.validation_error("metadata must be valid JSON", field="metadata") from exc
    if not isinstance(value, dict):
        raise errors.validation_error("metadata must be a JSON object", field="metadata")
    try:
        return check_metadata(value)
    except ValueError as exc:
        raise errors.validation_error(str(exc), field="metadata") from exc


@router.post(
    "/projects/{project_id}/evidence",
    response_model=Evidence,
    status_code=status.HTTP_201_CREATED,
    summary="Add evidence: a file, a written note, or both",
)
def upload_evidence(
    project_id: UUID,
    library: EvidenceLibrary,
    background: BackgroundTasks,
    file: Annotated[
        UploadFile | None,
        File(description="Photo, PDF, Word, Excel, text or CSV file, up to 50 MB."),
    ] = None,
    title: Annotated[str | None, Form(max_length=200)] = None,
    description: Annotated[str, Form(max_length=5000)] = "",
    evidence_type: Annotated[EvidenceType | None, Form()] = None,
    captured_at: Annotated[
        AwareDatetime | None,
        Form(description="When it was captured on site, with a timezone. Defaults to now."),
    ] = None,
    metadata: Annotated[
        str | None,
        Form(description='A JSON object, e.g. {"location": "Level 3", "source": "mobile_upload"}'),
    ] = None,
) -> Evidence:
    """Send `multipart/form-data`. A record needs a `file`, a `description`, or both."""
    data = None
    filename = None
    if file is not None and (file.filename or file.size):
        data = uploads.read_upload(file, max_bytes=MAX_EVIDENCE_BYTES, what="Evidence files")
        filename = file.filename
    evidence = library.upload(
        project_id,
        filename=filename,
        data=data,
        title=title,
        description=description,
        evidence_type=evidence_type,
        captured_at=captured_at,
        metadata=_parse_metadata(metadata),
    )
    background.add_task(library.run_processing, evidence.id)
    return evidence


@router.get(
    "/projects/{project_id}/evidence",
    response_model=EvidenceList,
    summary="List and search a project's evidence",
)
def list_evidence(
    project_id: UUID,
    library: EvidenceLibrary,
    q: Annotated[
        str | None, Query(max_length=200, description="Search title, description, code, filename.")
    ] = None,
    evidence_type: EvidenceType | None = None,
    captured_from: Annotated[
        date | None, Query(alias="from", description="Captured on or after this day (UTC).")
    ] = None,
    captured_to: Annotated[
        date | None, Query(alias="to", description="Captured on or before this day (UTC).")
    ] = None,
    archived: Annotated[
        bool | None, Query(description="true: archived only. false: active only. Omit for both.")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EvidenceList:
    filters = EvidenceFilters(
        q=q,
        evidence_type=evidence_type,
        captured_from=captured_from,
        captured_to=captured_to,
        archived=archived,
        limit=limit,
        offset=offset,
    )
    return EvidenceList(items=library.list_for_project(project_id, filters))


@router.get(
    "/evidence/{evidence_id}",
    response_model=EvidenceDetail,
    summary="Get one evidence record with a download link",
)
def get_evidence(evidence_id: UUID, library: EvidenceLibrary) -> EvidenceDetail:
    return library.get(evidence_id)


@router.patch(
    "/evidence/{evidence_id}",
    response_model=Evidence,
    summary="Edit evidence details, or archive and restore it",
)
def update_evidence(evidence_id: UUID, body: EvidenceUpdate, library: EvidenceLibrary) -> Evidence:
    return library.update(evidence_id, body.changes())


@router.post(
    "/evidence/{evidence_id}/process",
    response_model=Evidence,
    summary="Send evidence for AI processing again",
)
def retry_evidence_processing(
    evidence_id: UUID, library: EvidenceLibrary, background: BackgroundTasks
) -> Evidence:
    evidence = library.retry_processing(evidence_id)
    background.add_task(library.run_processing, evidence.id)
    return evidence
