"""Data access for contracts and contract items.

ContractRepository is the interface the service depends on.
SupabaseContractRepository acts as the signed-in user, so Row Level Security
limits every query to their organisation's projects. A contract in another
organisation simply is not returned.
"""

from typing import Any, Protocol
from uuid import UUID

from app.db.supabase import SupabaseRest
from app.schemas.contracts import Contract, ContractItem


class ContractRepository(Protocol):
    def project_exists(self, project_id: UUID) -> bool: ...

    def create_contract(self, values: dict[str, Any]) -> Contract: ...

    def list_contracts(self, project_id: UUID) -> list[Contract]: ...

    def get_contract(self, contract_id: UUID) -> Contract | None: ...

    def update_processing(self, contract_id: UUID, changes: dict[str, Any]) -> Contract | None: ...

    def list_items(self, contract_id: UUID) -> list[ContractItem]: ...

    def delete_untouched_drafts(self, contract_id: UUID) -> None: ...

    def add_items(self, rows: list[dict[str, Any]]) -> list[ContractItem]: ...

    def update_item(self, item_id: UUID, changes: dict[str, Any]) -> ContractItem | None: ...

    def delete_contract(self, contract_id: UUID) -> bool: ...

    def delete_item(self, item_id: UUID) -> bool: ...


class SupabaseContractRepository:
    def __init__(self, rest: SupabaseRest) -> None:
        self._rest = rest

    def project_exists(self, project_id: UUID) -> bool:
        return bool(self._rest.select("projects", {"id": f"eq.{project_id}"}, columns="id"))

    def create_contract(self, values: dict[str, Any]) -> Contract:
        # uploaded_by is filled in by the database from the caller.
        return Contract.model_validate(self._rest.insert("contracts", values))

    def list_contracts(self, project_id: UUID) -> list[Contract]:
        rows = self._rest.select(
            "contracts", {"project_id": f"eq.{project_id}"}, order="created_at.desc,id.asc"
        )
        return [Contract.model_validate(row) for row in rows]

    def get_contract(self, contract_id: UUID) -> Contract | None:
        rows = self._rest.select("contracts", {"id": f"eq.{contract_id}"}, limit=1)
        return Contract.model_validate(rows[0]) if rows else None

    def update_processing(self, contract_id: UUID, changes: dict[str, Any]) -> Contract | None:
        rows = self._rest.update("contracts", {"id": f"eq.{contract_id}"}, changes)
        return Contract.model_validate(rows[0]) if rows else None

    def list_items(self, contract_id: UUID) -> list[ContractItem]:
        rows = self._rest.select(
            "contract_items", {"contract_id": f"eq.{contract_id}"}, order="sort_order.asc,id.asc"
        )
        return [ContractItem.model_validate(row) for row in rows]

    def delete_untouched_drafts(self, contract_id: UUID) -> None:
        # The database policy only lets untouched drafts go; the filters say the same thing.
        self._rest.delete(
            "contract_items",
            {
                "contract_id": f"eq.{contract_id}",
                "review_status": "eq.draft",
                "edited_by_human": "is.false",
            },
        )

    def add_items(self, rows: list[dict[str, Any]]) -> list[ContractItem]:
        return [
            ContractItem.model_validate(row)
            for row in self._rest.insert_many("contract_items", rows)
        ]

    def update_item(self, item_id: UUID, changes: dict[str, Any]) -> ContractItem | None:
        # The database records who reviewed the item and flags human edits.
        rows = self._rest.update("contract_items", {"id": f"eq.{item_id}"}, changes)
        return ContractItem.model_validate(rows[0]) if rows else None

    def delete_contract(self, contract_id: UUID) -> bool:
        # Its items go with it (on delete cascade).
        return bool(self._rest.delete("contracts", {"id": f"eq.{contract_id}"}))

    def delete_item(self, item_id: UUID) -> bool:
        return bool(self._rest.delete("contract_items", {"id": f"eq.{item_id}"}))
