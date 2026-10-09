"""Evidence understanding schemas."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class EvidenceUnderstandingRequest(BaseModel):
    evidence_id: UUID
    project_id: UUID
    evidence_type: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    captured_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    original_filename: str | None = None
    mime_type: str | None = None
    document_url: str | None = None


class EvidenceSignals(BaseModel):
    """Structured signals inferred from evidence.

    These are review aids. They are not proof of entitlement, compliance, or
    legal validity.
    """

    objects: list[str] = Field(default_factory=list)
    activities: list[str] = Field(default_factory=list)
    extracted_text: str | None = None
    location: str | None = None
    date: datetime | None = None
    other_signals: dict[str, Any] = Field(default_factory=dict)


class EvidenceUnderstandingResult(BaseModel):
    evidence_id: UUID
    signals: EvidenceSignals
    confidence: float = Field(ge=0, le=1)
