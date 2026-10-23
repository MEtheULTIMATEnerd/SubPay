"""Contract upload and management (F03), the extraction workflow (F04) and
human review of the extracted line items (F05).

A contract or item in another organisation is indistinguishable from one that
does not exist: both are a 404.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, File, UploadFile, status

from app.api.deps import Contracts
from app.schemas.contracts import (
    Contract,
    ContractDetail,
    ContractItem,
    ContractItemList,
    ContractItemUpdate,
    ContractList,
)
from app.services import uploads
from app.services.contracts import MAX_CONTRACT_BYTES

router = APIRouter(tags=["contracts"])


@router.post(
    "/projects/{project_id}/contracts",
    response_model=Contract,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a contract and start extraction",
)
def upload_contract(
    project_id: UUID,
    contracts: Contracts,
    background: BackgroundTasks,
    file: Annotated[UploadFile, File(description="The contract: PDF or DOCX, up to 25 MB.")],
) -> Contract:
    """The response comes back straight away with `processing_status: "processing"`.
    Poll `GET /contracts/{contract_id}` until it is `ready` or `failed`."""
    data = uploads.read_upload(file, max_bytes=MAX_CONTRACT_BYTES, what="Contract")
    contract = contracts.upload(project_id, file.filename, data)
    background.add_task(contracts.run_extraction, contract.id)
    return contract


@router.get(
    "/projects/{project_id}/contracts",
    response_model=ContractList,
    summary="List a project's contracts",
)
def list_contracts(project_id: UUID, contracts: Contracts) -> ContractList:
    return ContractList(items=contracts.list_for_project(project_id))


@router.get(
    "/contracts/{contract_id}",
    response_model=ContractDetail,
    summary="Get one contract with a download link",
)
def get_contract(contract_id: UUID, contracts: Contracts) -> ContractDetail:
    return contracts.get(contract_id)


@router.delete(
    "/contracts/{contract_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a contract, its line items and the stored document",
)
def delete_contract(contract_id: UUID, contracts: Contracts) -> None:
    contracts.delete(contract_id)


@router.post(
    "/contracts/{contract_id}/extract",
    response_model=Contract,
    summary="Run extraction again after a failure",
)
def retry_extraction(
    contract_id: UUID, contracts: Contracts, background: BackgroundTasks
) -> Contract:
    contract = contracts.retry_extraction(contract_id)
    background.add_task(contracts.run_extraction, contract.id)
    return contract


@router.get(
    "/contracts/{contract_id}/items",
    response_model=ContractItemList,
    summary="List the contract's extracted line items",
)
def list_contract_items(contract_id: UUID, contracts: Contracts) -> ContractItemList:
    return ContractItemList(items=contracts.list_items(contract_id))


@router.patch(
    "/contract-items/{item_id}",
    response_model=ContractItem,
    summary="Correct an extracted line item",
)
def edit_contract_item(
    item_id: UUID, body: ContractItemUpdate, contracts: Contracts
) -> ContractItem:
    """A human edit. The item is flagged `edited_by_human` and the AI's original
    values stay in `extracted_values`."""
    return contracts.edit_item(item_id, body.changes())


@router.post(
    "/contract-items/{item_id}/confirm",
    response_model=ContractItem,
    summary="Confirm a line item",
)
def confirm_contract_item(item_id: UUID, contracts: Contracts) -> ContractItem:
    return contracts.review_item(item_id, "confirmed")


@router.post(
    "/contract-items/{item_id}/reject",
    response_model=ContractItem,
    summary="Reject a line item",
)
def reject_contract_item(item_id: UUID, contracts: Contracts) -> ContractItem:
    return contracts.review_item(item_id, "rejected")


@router.post(
    "/contract-items/{item_id}/reopen",
    response_model=ContractItem,
    summary="Return a line item to draft",
)
def reopen_contract_item(item_id: UUID, contracts: Contracts) -> ContractItem:
    return contracts.review_item(item_id, "draft")


@router.delete(
    "/contract-items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a line item the AI got wrong",
)
def delete_contract_item(item_id: UUID, contracts: Contracts) -> None:
    contracts.delete_item(item_id)
