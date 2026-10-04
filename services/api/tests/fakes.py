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
from app.repositories.platform import NO_PROFILE_MESSAGE
from app.schemas.platform import Me, Organisation, Profile, Project, ProjectStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FakeDatabase:
    def __init__(self) -> None:
        self.organisations: dict[UUID, dict[str, Any]] = {}
        self.profiles: dict[UUID, dict[str, Any]] = {}
        self.projects: dict[UUID, dict[str, Any]] = {}

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
