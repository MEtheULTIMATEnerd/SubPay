"""The contract workflow (F03, F04): upload, store, extract, save the items.

    upload contract  ->  stored  ->  extraction  ->  contract items (drafts)  ->  human review

The AI only ever produces drafts. Confirming, editing and rejecting items are
separate human actions.
"""

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from app.ai.extraction import (
    AI_UNAVAILABLE_MESSAGE,
    AiUnavailableError,
    ExtractionProvider,
    ExtractionRequest,
)
from app.core import errors
from app.db.storage import FileStorage
from app.repositories.contracts import ContractRepository
from app.schemas.contracts import Contract, ContractDetail, ContractItem, ReviewStatus
from app.services import uploads

logger = logging.getLogger("subpay.api.contracts")

BUCKET = "contracts"
MAX_CONTRACT_BYTES = 25 * 1024 * 1024
# A contract stuck in "processing" this long (for example after a server restart) can be retried.
STALE_PROCESSING = timedelta(minutes=10)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _object_path(contract: Contract) -> str:
    """storage_path is '<bucket>/<object path>'; storage wants the object path."""
    return contract.storage_path.split("/", 1)[1]


class ContractService:
    def __init__(
        self,
        repository: ContractRepository,
        storage: FileStorage,
        extractor: ExtractionProvider,
        *,
        signed_url_seconds: int = 300,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._extractor = extractor
        self._signed_url_seconds = signed_url_seconds

    # ---- upload --------------------------------------------------------------

    def upload(self, project_id: UUID, filename: str | None, data: bytes) -> Contract:
        """Store the document and record it. The caller then schedules run_extraction()."""
        if not self._repository.project_exists(project_id):
            raise errors.not_found("Project")

        display_name = uploads.clean_filename(filename, fallback="contract")
        kind = uploads.contract_kind(display_name, data)

        contract_id = uuid4()
        object_path = f"{project_id}/{contract_id}/original.{kind.extension}"
        self._storage.upload(BUCKET, object_path, data, kind.mime_type)

        contract = self._repository.create_contract(
            {
                "id": str(contract_id),
                "project_id": str(project_id),
                "original_filename": display_name,
                "storage_path": f"{BUCKET}/{object_path}",
                "mime_type": kind.mime_type,
                "size_bytes": len(data),
            }
        )
        return self._mark_processing(contract)

    # ---- read ----------------------------------------------------------------

    def list_for_project(self, project_id: UUID) -> list[Contract]:
        if not self._repository.project_exists(project_id):
            raise errors.not_found("Project")
        return self._repository.list_contracts(project_id)

    def get(self, contract_id: UUID) -> ContractDetail:
        contract = self._require(contract_id)
        url = self._storage.signed_url(
            BUCKET,
            _object_path(contract),
            expires_in=self._signed_url_seconds,
            download_as=contract.original_filename,
        )
        return ContractDetail(**contract.model_dump(), download_url=url)

    def list_items(self, contract_id: UUID) -> list[ContractItem]:
        self._require(contract_id)
        return self._repository.list_items(contract_id)

    # ---- extraction ----------------------------------------------------------

    def retry_extraction(self, contract_id: UUID) -> Contract:
        """Start extraction again after a failure. The caller then schedules run_extraction()."""
        contract = self._require(contract_id)
        if contract.processing_status == "ready":
            raise errors.conflict("This contract has already been extracted")
        if contract.processing_status == "processing":
            age = datetime.now(timezone.utc) - contract.updated_at
            if age < STALE_PROCESSING:
                raise errors.conflict("This contract is still being processed")
        return self._mark_processing(contract)

    def run_extraction(self, contract_id: UUID) -> None:
        """Runs after the response has been sent. Never raises: the outcome is
        recorded on the contract as 'ready' or 'failed'."""
        try:
            contract = self._repository.get_contract(contract_id)
            if contract is None:
                return
            request = ExtractionRequest(
                contract_id=contract.id,
                original_filename=contract.original_filename,
                mime_type=contract.mime_type,
                document_url=self._storage.signed_url(
                    BUCKET, _object_path(contract), expires_in=self._signed_url_seconds
                ),
            )
            result = self._extractor.extract(request)
            saved = self._save_drafts(contract.id, result.items)
            self._repository.update_processing(
                contract.id,
                {"processing_status": "ready", "error": None, "processed_at": _now()},
            )
            logger.info("Extracted %d items for contract %s", saved, contract.id)
        except AiUnavailableError as exc:
            self._mark_failed(contract_id, str(exc))
        except Exception:
            logger.exception("Extraction failed for contract %s", contract_id)
            self._mark_failed(contract_id, AI_UNAVAILABLE_MESSAGE)

    def _save_drafts(self, contract_id: UUID, items: list) -> int:
        """Replace untouched AI drafts with the new result. Anything a person has
        edited, confirmed or rejected is kept, and not duplicated."""
        self._repository.delete_untouched_drafts(contract_id)
        kept_codes = {item.item_code for item in self._repository.list_items(contract_id)}
        rows = []
        for position, item in enumerate(items):
            if item.item_code in kept_codes:
                continue
            values = item.model_dump(mode="json")
            confidence = values.pop("confidence")
            rows.append(
                {
                    **values,
                    "contract_id": str(contract_id),
                    "extraction_confidence": confidence,
                    # The AI's answer exactly as given, kept even if a person edits the item.
                    "extracted_values": {**values, "confidence": confidence},
                    "sort_order": position,
                }
            )
        return len(self._repository.add_items(rows))

    # ---- human review (F05) --------------------------------------------------

    def edit_item(self, item_id: UUID, changes: dict) -> ContractItem:
        """A person corrects an extracted item. The AI's original values are kept
        in extracted_values and the item is flagged as edited by the database."""
        item = self._repository.update_item(item_id, changes)
        if item is None:
            raise errors.not_found("Contract item")
        return item

    def review_item(self, item_id: UUID, status: ReviewStatus) -> ContractItem:
        """Confirm, reject or reopen an item. The database records who did it."""
        item = self._repository.update_item(item_id, {"review_status": status})
        if item is None:
            raise errors.not_found("Contract item")
        return item

    def delete_item(self, item_id: UUID) -> None:
        """Remove an item the AI got wrong."""
        if not self._repository.delete_item(item_id):
            raise errors.not_found("Contract item")

    # ---- delete --------------------------------------------------------------

    def delete(self, contract_id: UUID) -> None:
        """Remove the contract, its items and the stored document."""
        contract = self._require(contract_id)
        if not self._repository.delete_contract(contract_id):
            raise errors.not_found("Contract")
        try:
            self._storage.delete(BUCKET, _object_path(contract))
        except Exception:
            # The record is gone and the file is private, so a leftover file is harmless.
            logger.exception("Could not delete the stored file for contract %s", contract_id)

    # ---- helpers -------------------------------------------------------------

    def _require(self, contract_id: UUID) -> Contract:
        contract = self._repository.get_contract(contract_id)
        if contract is None:
            raise errors.not_found("Contract")
        return contract

    def _mark_processing(self, contract: Contract) -> Contract:
        updated = self._repository.update_processing(
            contract.id, {"processing_status": "processing", "error": None}
        )
        return updated or contract

    def _mark_failed(self, contract_id: UUID, message: str) -> None:
        try:
            self._repository.update_processing(
                contract_id, {"processing_status": "failed", "error": message}
            )
        except Exception:
            logger.exception("Could not record the failed extraction for contract %s", contract_id)
