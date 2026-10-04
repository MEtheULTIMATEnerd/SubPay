"""Response shapes for contracts and contract items (F03 to F05).

Field names match the database columns in docs/database-schema.md.
"""

from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

ProcessingStatus = Literal["uploaded", "processing", "ready", "failed"]
ReviewStatus = Literal["draft", "confirmed", "rejected"]


class Contract(BaseModel):
    id: UUID
    project_id: UUID
    original_filename: str
    storage_path: str
    mime_type: str
    size_bytes: int
    page_count: int | None
    processing_status: ProcessingStatus
    error: str | None
    uploaded_by: UUID | None
    created_at: datetime
    updated_at: datetime
    processed_at: datetime | None


class ContractDetail(Contract):
    # Short-lived signed link to the stored document. Null if it cannot be issued.
    download_url: str | None = None


class ContractList(BaseModel):
    items: list[Contract]


class ContractItem(BaseModel):
    id: UUID
    contract_id: UUID
    item_code: str
    description: str
    quantity: float | None
    unit: str | None
    rate: float | None
    amount: float | None
    conditions: str | None
    notice_requirement: str | None
    due_date: date | None
    extraction_confidence: float | None
    review_status: ReviewStatus
    edited_by_human: bool
    reviewed_by: UUID | None
    source_reference: str | None
    extracted_values: dict[str, Any] | None
    sort_order: int
    created_at: datetime
    updated_at: datetime


class ContractItemList(BaseModel):
    items: list[ContractItem]


Description = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]
OptionalText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
Amount = Annotated[float, Field(ge=0)]

_TEXT_FIELDS = ("unit", "conditions", "notice_requirement")


class ContractItemUpdate(BaseModel):
    """PATCH body for a human edit: only the fields that are sent are changed.

    Review status is not editable here; confirming and rejecting are their own
    actions. The AI's confidence and original values can never be changed.
    """

    description: Description | None = None
    quantity: Amount | None = None
    unit: OptionalText | None = None
    rate: Amount | None = None
    amount: Amount | None = None
    conditions: OptionalText | None = None
    notice_requirement: OptionalText | None = None
    due_date: date | None = None

    @field_validator(*_TEXT_FIELDS, mode="after")
    @classmethod
    def _blank_means_not_in_the_contract(cls, value: str | None) -> str | None:
        return value or None

    @model_validator(mode="after")
    def _validate(self) -> "ContractItemUpdate":
        if not self.model_fields_set:
            raise ValueError("Send at least one field to update")
        if "description" in self.model_fields_set and self.description is None:
            raise ValueError("description cannot be null")
        return self

    def changes(self) -> dict[str, Any]:
        """The fields the client actually sent, ready to store."""
        return self.model_dump(exclude_unset=True, mode="json")
