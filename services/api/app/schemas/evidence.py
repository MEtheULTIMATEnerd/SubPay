"""Request and response shapes for evidence (F06, F07).

Field names match the database columns in docs/database-schema.md.
"""

import json
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, StringConstraints, field_validator, model_validator

from app.schemas.contracts import ProcessingStatus

EvidenceType = Literal["photo", "document", "docket", "message", "other"]

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]

MAX_METADATA_CHARACTERS = 10_000


def check_metadata(value: dict[str, Any]) -> dict[str, Any]:
    if len(json.dumps(value)) > MAX_METADATA_CHARACTERS:
        raise ValueError("metadata is too large")
    return value


class Evidence(BaseModel):
    id: UUID
    project_id: UUID
    sequence_number: int
    code: str
    uploaded_by: UUID | None
    storage_path: str | None
    original_filename: str | None
    mime_type: str | None
    size_bytes: int | None
    evidence_type: EvidenceType
    captured_at: datetime
    title: str
    description: str
    metadata: dict[str, Any]
    processing_status: ProcessingStatus
    archived: bool
    created_at: datetime
    updated_at: datetime
    # Signed link for showing a photo. Null for anything a browser cannot display.
    preview_url: str | None = None


class EvidenceDetail(Evidence):
    # Short-lived signed link to the stored file. Null for a written note.
    download_url: str | None = None


class EvidenceList(BaseModel):
    items: list[Evidence]


class EvidenceUpdate(BaseModel):
    """PATCH body: only the fields that are sent are changed.

    The stored file, the code, the uploader and the project cannot be changed.
    """

    title: Title | None = None
    description: Description | None = None
    evidence_type: EvidenceType | None = None
    # Must say which timezone it is in, e.g. 2026-09-14T11:30:00+10:00.
    captured_at: AwareDatetime | None = None
    # Replaces the whole metadata object.
    metadata: dict[str, Any] | None = None
    archived: bool | None = None

    @field_validator("metadata", mode="after")
    @classmethod
    def _metadata_size(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return value if value is None else check_metadata(value)

    @model_validator(mode="after")
    def _validate(self) -> "EvidenceUpdate":
        if not self.model_fields_set:
            raise ValueError("Send at least one field to update")
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self

    def changes(self) -> dict[str, Any]:
        """The fields the client actually sent, ready to store."""
        changes = self.model_dump(exclude_unset=True, mode="json")
        if self.captured_at is not None:
            changes["captured_at"] = self.captured_at.astimezone(timezone.utc).isoformat()
        return changes
