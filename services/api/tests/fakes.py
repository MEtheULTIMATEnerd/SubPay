"""In-memory stand-in for the platform repository.

It mimics what the database does for a signed-in user: every read and write is
limited to that user's organisation, and server-set columns are filled in from
the caller. This lets the endpoint tests run without Supabase.

It does NOT prove that Row Level Security works. That is checked against a
real database by supabase/tests/platform_foundation.sql.
"""

from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from app.core import errors
from app.core.errors import ApiError
from app.repositories.evidence import EvidenceFilters
from app.repositories.platform import NO_PROFILE_MESSAGE
from app.schemas.contracts import Contract, ContractItem
from app.schemas.evidence import Evidence
from app.schemas.platform import Me, Organisation, Profile, Project, ProjectStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FakeDatabase:
    def __init__(self) -> None:
        self.organisations: dict[UUID, dict[str, Any]] = {}
        self.profiles: dict[UUID, dict[str, Any]] = {}
        self.projects: dict[UUID, dict[str, Any]] = {}
        self.contracts: dict[UUID, dict[str, Any]] = {}
        self.contract_items: dict[UUID, dict[str, Any]] = {}
        self.evidence: dict[UUID, dict[str, Any]] = {}

    def organisation_of(self, user_id: UUID) -> UUID | None:
        profile = self.profiles.get(user_id)
        return profile["organisation_id"] if profile else None

    def can_access_project(self, user_id: UUID, project_id: UUID) -> bool:
        project = self.projects.get(project_id)
        organisation_id = self.organisation_of(user_id)
        return bool(project and organisation_id and project["organisation_id"] == organisation_id)

    def add_organisation(self, name: str) -> UUID:
        org_id = uuid4()
        self.organisations[org_id] = {
            "id": org_id,
            "name": name,
            "created_at": _now(),
            "updated_at": _now(),
        }
        return org_id

    def add_profile(
        self, user_id: str, organisation_id: UUID, full_name: str, role: str = "owner"
    ) -> UUID:
        uid = UUID(user_id)
        self.profiles[uid] = {
            "id": uid,
            "organisation_id": organisation_id,
            "email": f"{full_name.split()[0].lower()}@subpay.test",
            "full_name": full_name,
            "role": role,
            "created_at": _now(),
            "updated_at": _now(),
        }
        return uid


class FakePlatformRepository:
    def __init__(self, db: FakeDatabase, user_id: UUID) -> None:
        self._db = db
        self._user_id = user_id

    @property
    def _organisation_id(self) -> UUID | None:
        profile = self._db.profiles.get(self._user_id)
        return profile["organisation_id"] if profile else None

    def _visible(self, project_id: UUID) -> dict[str, Any] | None:
        row = self._db.projects.get(project_id)
        if row is None or row["organisation_id"] != self._organisation_id:
            return None
        return row

    def get_me(self) -> Me | None:
        profile = self._db.profiles.get(self._user_id)
        if profile is None:
            return None
        return Me(
            profile=Profile.model_validate(profile),
            organisation=Organisation.model_validate(
                self._db.organisations[profile["organisation_id"]]
            ),
        )

    def update_my_name(self, full_name: str) -> Me | None:
        profile = self._db.profiles.get(self._user_id)
        if profile is None:
            return None
        profile.update(full_name=full_name, updated_at=_now())
        return self.get_me()

    def list_projects(
        self, *, status: ProjectStatus | None, limit: int, offset: int
    ) -> list[Project]:
        rows = [
            r
            for r in self._db.projects.values()
            if r["organisation_id"] == self._organisation_id
            and (status is None or r["status"] == status)
        ]
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        return [Project.model_validate(r) for r in rows[offset : offset + limit]]

    def get_project(self, project_id: UUID) -> Project | None:
        row = self._visible(project_id)
        return Project.model_validate(row) if row else None

    def create_project(self, values: dict[str, Any]) -> Project:
        if self._organisation_id is None:
            raise errors.forbidden(NO_PROFILE_MESSAGE)
        project_id = uuid4()
        row = {
            "site_address": "",
            "start_date": None,
            "end_date": None,
            **values,
            "id": project_id,
            "organisation_id": self._organisation_id,
            "status": "active",
            "created_by": self._user_id,
            "created_at": _now(),
            "updated_at": _now(),
        }
        self._db.projects[project_id] = row
        return Project.model_validate(row)

    def update_project(self, project_id: UUID, changes: dict[str, Any]) -> Project | None:
        row = self._visible(project_id)
        if row is None:
            return None
        candidate = {**row, **changes}
        start, end = candidate["start_date"], candidate["end_date"]
        if start and end and date.fromisoformat(str(end)) < date.fromisoformat(str(start)):
            # The database check constraint projects_dates_check.
            raise errors.validation_error(
                "End date must not be before start date", field="end_date"
            )
        row.update(changes, updated_at=_now())
        return Project.model_validate(row)


class FakeContractRepository:
    """Contracts and items for one caller, limited to their organisation's projects."""

    def __init__(self, db: FakeDatabase, user_id: UUID) -> None:
        self._db = db
        self._user_id = user_id

    def _visible(self, contract_id: UUID) -> dict[str, Any] | None:
        row = self._db.contracts.get(contract_id)
        if row is None or not self._db.can_access_project(self._user_id, row["project_id"]):
            return None
        return row

    def project_exists(self, project_id: UUID) -> bool:
        return self._db.can_access_project(self._user_id, project_id)

    def create_contract(self, values: dict[str, Any]) -> Contract:
        project_id = UUID(values["project_id"])
        if not self._db.can_access_project(self._user_id, project_id):
            raise errors.forbidden()  # what the database's row-level security does
        contract_id = UUID(values["id"])
        row = {
            **values,
            "id": contract_id,
            "project_id": project_id,
            "page_count": None,
            "processing_status": "uploaded",
            "error": None,
            "uploaded_by": self._user_id,
            "created_at": _now(),
            "updated_at": _now(),
            "processed_at": None,
        }
        self._db.contracts[contract_id] = row
        return Contract.model_validate(row)

    def list_contracts(self, project_id: UUID) -> list[Contract]:
        if not self._db.can_access_project(self._user_id, project_id):
            return []
        rows = [r for r in self._db.contracts.values() if r["project_id"] == project_id]
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        return [Contract.model_validate(r) for r in rows]

    def get_contract(self, contract_id: UUID) -> Contract | None:
        row = self._visible(contract_id)
        return Contract.model_validate(row) if row else None

    def update_processing(self, contract_id: UUID, changes: dict[str, Any]) -> Contract | None:
        row = self._visible(contract_id)
        if row is None:
            return None
        row.update(changes, updated_at=_now())
        return Contract.model_validate(row)

    def list_items(self, contract_id: UUID) -> list[ContractItem]:
        if self._visible(contract_id) is None:
            return []
        rows = [r for r in self._db.contract_items.values() if r["contract_id"] == contract_id]
        rows.sort(key=lambda r: r["sort_order"])
        return [ContractItem.model_validate(r) for r in rows]

    def delete_untouched_drafts(self, contract_id: UUID) -> None:
        if self._visible(contract_id) is None:
            return
        for item_id, row in list(self._db.contract_items.items()):
            if (
                row["contract_id"] == contract_id
                and row["review_status"] == "draft"
                and not row["edited_by_human"]
            ):
                del self._db.contract_items[item_id]

    def add_items(self, rows: list[dict[str, Any]]) -> list[ContractItem]:
        added = []
        for values in rows:
            contract_id = UUID(values["contract_id"])
            if self._visible(contract_id) is None:
                raise errors.forbidden()
            item_id = uuid4()
            row = {
                **values,
                "id": item_id,
                "contract_id": contract_id,
                "review_status": "draft",
                "edited_by_human": False,
                "reviewed_by": None,
                "created_at": _now(),
                "updated_at": _now(),
            }
            self._db.contract_items[item_id] = row
            added.append(ContractItem.model_validate(row))
        return added

    _CONTENT_FIELDS = (
        "item_code", "description", "quantity", "unit", "rate", "amount",
        "conditions", "notice_requirement", "due_date",
    )  # fmt: skip

    def update_item(self, item_id: UUID, changes: dict[str, Any]) -> ContractItem | None:
        row = self._db.contract_items.get(item_id)
        if row is None or self._visible(row["contract_id"]) is None:
            return None
        before = dict(row)
        row.update(changes, updated_at=_now())
        # What the database trigger contract_items_track_review does:
        if any(row.get(f) != before.get(f) for f in self._CONTENT_FIELDS):
            row["edited_by_human"] = True
        if row["review_status"] != before["review_status"]:
            row["reviewed_by"] = None if row["review_status"] == "draft" else self._user_id
        return ContractItem.model_validate(row)


class FakeStorage:
    """Files kept in memory. Like the real buckets: private, and never overwritten."""

    def __init__(self) -> None:
        self.files: dict[tuple[str, str], tuple[bytes, str]] = {}
        self.fail_uploads = False
        self.batch_sign_calls: list[list[str]] = []

    def upload(self, bucket: str, path: str, content: bytes, content_type: str) -> None:
        if self.fail_uploads:
            raise errors.service_unavailable()
        if (bucket, path) in self.files:
            raise ApiError(409, "conflict", "That file has already been uploaded")
        self.files[(bucket, path)] = (content, content_type)

    def signed_url(
        self, bucket: str, path: str, *, expires_in: int, download_as: str | None = None
    ) -> str | None:
        if (bucket, path) not in self.files:
            return None
        return f"https://storage.test/{bucket}/{path}?token=signed&expires={expires_in}"

    def signed_urls(self, bucket: str, paths: list[str], *, expires_in: int) -> dict[str, str]:
        self.batch_sign_calls.append(list(paths))
        links = {p: self.signed_url(bucket, p, expires_in=expires_in) for p in paths}
        return {p: url for p, url in links.items() if url}


class FakeEvidenceRepository:
    """Evidence for one caller, limited to their organisation's projects."""

    def __init__(self, db: FakeDatabase, user_id: UUID) -> None:
        self._db = db
        self._user_id = user_id

    def _visible(self, evidence_id: UUID) -> dict[str, Any] | None:
        row = self._db.evidence.get(evidence_id)
        if row is None or not self._db.can_access_project(self._user_id, row["project_id"]):
            return None
        return row

    def project_exists(self, project_id: UUID) -> bool:
        return self._db.can_access_project(self._user_id, project_id)

    def create(self, values: dict[str, Any]) -> Evidence:
        project_id = UUID(values["project_id"])
        if not self._db.can_access_project(self._user_id, project_id):
            raise errors.forbidden()
        evidence_id = UUID(values["id"])
        # What the database trigger evidence_assign_code does:
        sequence = 1 + max(
            (
                r["sequence_number"]
                for r in self._db.evidence.values()
                if r["project_id"] == project_id
            ),
            default=0,
        )
        row = {
            "storage_path": None,
            "original_filename": None,
            "mime_type": None,
            "size_bytes": None,
            "evidence_type": "other",
            "captured_at": _now(),
            "description": "",
            "metadata": {},
            **values,
            "id": evidence_id,
            "project_id": project_id,
            "sequence_number": sequence,
            "code": f"EV-{sequence:03d}",
            "uploaded_by": self._user_id,
            "processing_status": "uploaded",
            "archived": False,
            "created_at": _now(),
            "updated_at": _now(),
        }
        self._db.evidence[evidence_id] = row
        return Evidence.model_validate(row)

    def list_for_project(self, project_id: UUID, filters: EvidenceFilters) -> list[Evidence]:
        if not self._db.can_access_project(self._user_id, project_id):
            return []
        rows = [Evidence.model_validate(r) for r in self._db.evidence.values()]
        rows = [r for r in rows if r.project_id == project_id]
        if filters.evidence_type:
            rows = [r for r in rows if r.evidence_type == filters.evidence_type]
        if filters.archived is not None:
            rows = [r for r in rows if r.archived == filters.archived]
        if filters.captured_from:
            rows = [r for r in rows if r.captured_at.date() >= filters.captured_from]
        if filters.captured_to:
            rows = [r for r in rows if r.captured_at.date() <= filters.captured_to]
        if filters.q and filters.q.strip():
            needle = filters.q.strip().lower()
            rows = [
                r
                for r in rows
                if needle
                in " ".join([r.title, r.description, r.code, r.original_filename or ""]).lower()
            ]
        rows.sort(key=lambda r: r.captured_at, reverse=True)
        return rows[filters.offset : filters.offset + filters.limit]

    def get(self, evidence_id: UUID) -> Evidence | None:
        row = self._visible(evidence_id)
        return Evidence.model_validate(row) if row else None

    def update(self, evidence_id: UUID, changes: dict[str, Any]) -> Evidence | None:
        row = self._visible(evidence_id)
        if row is None:
            return None
        candidate = {**row, **changes}
        if candidate["storage_path"] is None and not str(candidate["description"]).strip():
            # The database check constraint evidence_file_or_note_check.
            raise errors.validation_error("Add a file or a written note", field="description")
        row.update(changes, updated_at=_now())
        return Evidence.model_validate(row)
