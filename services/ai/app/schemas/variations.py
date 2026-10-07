"""Potential variation detection schemas."""

from uuid import UUID

from pydantic import BaseModel, Field, StrictBool

from app.schemas.evidence import EvidenceSignals
from app.schemas.matching import MatchSuggestion


class VariationDetectionRequest(BaseModel):
    evidence_id: UUID
    signals: EvidenceSignals
    matches: list[MatchSuggestion] = Field(default_factory=list)


class VariationDetectionResult(BaseModel):
    potential_variation: StrictBool
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=1000)
    related_evidence_ids: list[UUID] = Field(default_factory=list)
    review_required: StrictBool
