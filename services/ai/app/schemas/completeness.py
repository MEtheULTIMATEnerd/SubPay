"""Evidence support completeness schemas."""

from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import CompletenessStatus
from app.schemas.matching import MatchSuggestion


class CompletenessRequest(BaseModel):
    contract_item_id: UUID
    matches: list[MatchSuggestion] = Field(default_factory=list)


class CompletenessResult(BaseModel):
    contract_item_id: UUID
    status: CompletenessStatus
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=1000)
