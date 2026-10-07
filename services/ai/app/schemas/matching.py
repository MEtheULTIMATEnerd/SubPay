"""Evidence-to-contract matching schemas."""

from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import Assessment
from app.schemas.evidence import EvidenceSignals


class MatchingContractItem(BaseModel):
    """AI-service view of a confirmed contract item supplied by the caller."""

    contract_item_id: UUID
    item_code: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=1, max_length=2000)
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = None
    amount: float | None = Field(default=None, ge=0)


class MatchingRequest(BaseModel):
    evidence_id: UUID
    signals: EvidenceSignals
    contract_items: list[MatchingContractItem]


class MatchSuggestion(BaseModel):
    contract_item_id: UUID
    confidence: float = Field(ge=0, le=1)
    assessment: Assessment
    reason: str = Field(min_length=1, max_length=1000)
    missing_evidence: list[str] = Field(default_factory=list)


class MatchingResult(BaseModel):
    evidence_id: UUID
    matches: list[MatchSuggestion]

