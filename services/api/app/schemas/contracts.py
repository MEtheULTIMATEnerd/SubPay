"""Response shapes for contracts and contract items (F03 to F05).

Field names match the database columns in docs/database-schema.md.
"""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

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
