"""Contract extraction request and response schemas."""

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class ExtractionRequest(BaseModel):
    contract_id: UUID
    original_filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1)
    document_url: str | None = None


class ExtractedContractItem(BaseModel):
    """One contract schedule item extracted by AI.

    Only item_code, description and confidence are required. Missing contract
    information stays null rather than being guessed.
    """

    item_code: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=1, max_length=2000)
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = None
    rate: float | None = Field(default=None, ge=0)
    amount: float | None = Field(default=None, ge=0)
    conditions: str | None = None
    notice_requirement: str | None = None
    due_date: date | None = None
    confidence: float = Field(ge=0, le=1)
    source_reference: str | None = None


class ExtractionResult(BaseModel):
    contract_id: UUID
    items: list[ExtractedContractItem]

    @model_validator(mode="after")
    def _items_are_not_empty_strings(self) -> "ExtractionResult":
        # The item model catches blank required fields; this hook keeps a named
        # validation location for future cross-item checks without changing callers.
        return self
