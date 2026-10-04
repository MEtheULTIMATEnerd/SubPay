"""The evidence workflow (F06, F07): capture, store, describe, hand to AI.

    upload evidence  ->  stored  ->  metadata saved  ->  AI processing  ->  ready

Source files and their metadata are preserved. Evidence is archived, never
deleted, and the stored file cannot be replaced.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from app.ai.evidence import EvidenceProcessor, EvidenceRequest
from app.ai.extraction import AiUnavailableError
from app.core import errors
from app.db.storage import FileStorage
from app.repositories.evidence import EvidenceFilters, EvidenceRepository
from app.schemas.evidence import Evidence, EvidenceDetail
from app.services import uploads

logger = logging.getLogger("subpay.api.evidence")

BUCKET = "evidence"
MAX_EVIDENCE_BYTES = 50 * 1024 * 1024
# Evidence stuck in "processing" this long (for example after a server restart) can be retried.
STALE_PROCESSING = timedelta(minutes=10)


def _object_path(evidence: Evidence) -> str | None:
    """storage_path is '<bucket>/<object path>'; storage wants the object path."""
    return evidence.storage_path.split("/", 1)[1] if evidence.storage_path else None


def _default_type(kind: uploads.FileKind | None) -> str:
    if kind is None:
        return "message"
    return "photo" if kind.mime_type.startswith("image/") else "document"


class EvidenceService:
    def __init__(
        self,
        repository: EvidenceRepository,
        storage: FileStorage,
        processor: EvidenceProcessor,
        *,
        signed_url_seconds: int = 300,
        preview_url_seconds: int = 3600,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._processor = processor
        self._signed_url_seconds = signed_url_seconds
        self._preview_url_seconds = preview_url_seconds

    # ---- upload --------------------------------------------------------------

    def upload(
        self,
        project_id: UUID,
        *,
        filename: str | None,
        data: bytes | None,
        title: str | None,
        description: str,
        evidence_type: str | None,
        captured_at: datetime | None,
        metadata: dict[str, Any],
    ) -> Evidence:
        """Store the file (if any) and record the evidence.
        The caller then schedules run_processing()."""
        if not self._repository.project_exists(project_id):
            raise errors.not_found("Project")

        description = description.strip()
        if data is None and not description:
            raise errors.validation_error("Add a file or a written note", field="description")

        evidence_id = uuid4()
        values: dict[str, Any] = {
            "id": str(evidence_id),
            "project_id": str(project_id),
            "description": description,
            "metadata": metadata,
        }
        display_name = None
        kind = None
        if data is not None:
            display_name = uploads.clean_filename(filename, fallback="evidence")
            kind = uploads.evidence_kind(display_name, data)
            object_path = f"{project_id}/{evidence_id}/original.{kind.extension}"
            self._storage.upload(BUCKET, object_path, data, kind.mime_type)
            values.update(
                storage_path=f"{BUCKET}/{object_path}",
                original_filename=display_name,
                mime_type=kind.mime_type,
                size_bytes=len(data),
            )

        values["title"] = ((title or "").strip() or display_name or "Note")[:200]
        values["evidence_type"] = evidence_type or _default_type(kind)
        if captured_at is not None:
            values["captured_at"] = captured_at.astimezone(timezone.utc).isoformat()

        evidence = self._repository.create(values)
        return self._with_preview(self._mark_processing(evidence))

    # ---- read ----------------------------------------------------------------

    def list_for_project(self, project_id: UUID, filters: EvidenceFilters) -> list[Evidence]:
        if not self._repository.project_exists(project_id):
            raise errors.not_found("Project")
        records = self._repository.list_for_project(project_id, filters)

        # One request signs the preview links for every photo on the page.
        paths = [_object_path(r) for r in records if r.mime_type in uploads.PREVIEWABLE_MIME_TYPES]
        try:
            links = self._storage.signed_urls(
                BUCKET, [p for p in paths if p], expires_in=self._preview_url_seconds
            )
        except errors.ApiError as exc:
            if exc.status_code < 500:
                raise
            # The library still lists the evidence; the photos just have no preview.
            logger.warning("Could not sign evidence previews for project %s", project_id)
            links = {}
        return [
            r.model_copy(update={"preview_url": links.get(_object_path(r) or "")}) for r in records
        ]

    def get(self, evidence_id: UUID) -> EvidenceDetail:
        evidence = self._with_preview(self._require(evidence_id))
        path = _object_path(evidence)
        url = (
            self._storage.signed_url(
                BUCKET,
                path,
                expires_in=self._signed_url_seconds,
                download_as=evidence.original_filename,
            )
            if path
            else None
        )
        return EvidenceDetail(**evidence.model_dump(), download_url=url)

    # ---- edit ----------------------------------------------------------------

    def update(self, evidence_id: UUID, changes: dict[str, Any]) -> Evidence:
        evidence = self._repository.update(evidence_id, changes)
        if evidence is None:
            raise errors.not_found("Evidence")
        return self._with_preview(evidence)

    # ---- AI processing -------------------------------------------------------

    def retry_processing(self, evidence_id: UUID) -> Evidence:
        """Send the evidence to the AI service again. The caller then schedules run_processing()."""
        evidence = self._require(evidence_id)
        if evidence.processing_status == "ready":
            raise errors.conflict("This evidence has already been processed")
        if evidence.processing_status == "processing":
            age = datetime.now(timezone.utc) - evidence.updated_at
            if age < STALE_PROCESSING:
                raise errors.conflict("This evidence is still being processed")
        return self._with_preview(self._mark_processing(evidence))

    def run_processing(self, evidence_id: UUID) -> None:
        """Runs after the response has been sent. Never raises: the outcome is
        recorded on the evidence as 'ready' or 'failed'."""
        try:
            evidence = self._repository.get(evidence_id)
            if evidence is None:
                return
            path = _object_path(evidence)
            self._processor.process(
                EvidenceRequest(
                    evidence_id=evidence.id,
                    project_id=evidence.project_id,
                    evidence_type=evidence.evidence_type,
                    title=evidence.title,
                    description=evidence.description,
                    captured_at=evidence.captured_at,
                    metadata=evidence.metadata,
                    original_filename=evidence.original_filename,
                    mime_type=evidence.mime_type,
                    document_url=(
                        self._storage.signed_url(BUCKET, path, expires_in=self._signed_url_seconds)
                        if path
                        else None
                    ),
                )
            )
            self._repository.update(evidence.id, {"processing_status": "ready"})
        except AiUnavailableError:
            self._mark_failed(evidence_id)
        except Exception:
            logger.exception("Processing failed for evidence %s", evidence_id)
            self._mark_failed(evidence_id)

    # ---- helpers -------------------------------------------------------------

    def _require(self, evidence_id: UUID) -> Evidence:
        evidence = self._repository.get(evidence_id)
        if evidence is None:
            raise errors.not_found("Evidence")
        return evidence

    def _with_preview(self, evidence: Evidence) -> Evidence:
        path = _object_path(evidence)
        if not path or evidence.mime_type not in uploads.PREVIEWABLE_MIME_TYPES:
            return evidence
        url = self._storage.signed_url(BUCKET, path, expires_in=self._preview_url_seconds)
        return evidence.model_copy(update={"preview_url": url})

    def _mark_processing(self, evidence: Evidence) -> Evidence:
        updated = self._repository.update(evidence.id, {"processing_status": "processing"})
        return updated or evidence

    def _mark_failed(self, evidence_id: UUID) -> None:
        try:
            self._repository.update(evidence_id, {"processing_status": "failed"})
        except Exception:
            logger.exception("Could not record the failed processing for evidence %s", evidence_id)
