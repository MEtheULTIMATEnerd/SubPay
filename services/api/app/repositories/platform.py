"""Data access for profiles, organisations and projects.

PlatformRepository is the interface the endpoints depend on.
SupabasePlatformRepository is the real implementation. It acts as the signed-in
user, so Row Level Security limits every query to their organisation. That is
why nothing here filters by organisation_id: the database does it, and a row
in another organisation simply is not returned.
"""

from typing import Any, Protocol
from uuid import UUID

from app.core import errors
from app.db.supabase import DatabaseError, SupabaseRest
from app.schemas.platform import Me, Organisation, Profile, Project, ProjectStatus

NO_PROFILE_MESSAGE = "This account has no SubPay profile. Sign up again or contact support."

_NOT_NULL_VIOLATION = "23502"
_INSUFFICIENT_PRIVILEGE = "42501"

# Database check constraints -> the field and message shown to the user.
_PROJECT_CONSTRAINTS: dict[str, tuple[str, str]] = {
    "projects_dates_check": ("end_date", "End date must not be before start date"),
    "projects_name_length": ("name", "Project name must be 1 to 200 characters"),
    "projects_client_name_length": ("client_name", "Client name must be 1 to 200 characters"),
}


class PlatformRepository(Protocol):
    def get_me(self) -> Me | None: ...

    def update_my_name(self, full_name: str) -> Me | None: ...

    def list_projects(
        self, *, status: ProjectStatus | None, limit: int, offset: int
    ) -> list[Project]: ...

    def get_project(self, project_id: UUID) -> Project | None: ...

    def create_project(self, values: dict[str, Any]) -> Project: ...

    def update_project(self, project_id: UUID, changes: dict[str, Any]) -> Project | None: ...


class SupabasePlatformRepository:
    def __init__(self, rest: SupabaseRest, user_id: UUID) -> None:
        self._rest = rest
        self._user_id = user_id

    # ---- profile -------------------------------------------------------------

    def get_me(self) -> Me | None:
        profiles = self._rest.select("profiles", {"id": f"eq.{self._user_id}"}, limit=1)
        if not profiles:
            return None
        profile = Profile.model_validate(profiles[0])
        organisations = self._rest.select(
            "organisations", {"id": f"eq.{profile.organisation_id}"}, limit=1
        )
        if not organisations:
            return None
        return Me(profile=profile, organisation=Organisation.model_validate(organisations[0]))

    def update_my_name(self, full_name: str) -> Me | None:
        updated = self._rest.update(
            "profiles", {"id": f"eq.{self._user_id}"}, {"full_name": full_name}
        )
        if not updated:
            return None
        return self.get_me()

    def _has_profile(self) -> bool:
        return bool(self._rest.select("profiles", {"id": f"eq.{self._user_id}"}, columns="id"))

    # ---- projects ------------------------------------------------------------

    def list_projects(
        self, *, status: ProjectStatus | None, limit: int, offset: int
    ) -> list[Project]:
        filters = {"status": f"eq.{status}"} if status else {}
        rows = self._rest.select(
            "projects", filters, order="created_at.desc,id.asc", limit=limit, offset=offset
        )
        return [Project.model_validate(row) for row in rows]

    def get_project(self, project_id: UUID) -> Project | None:
        rows = self._rest.select("projects", {"id": f"eq.{project_id}"}, limit=1)
        return Project.model_validate(rows[0]) if rows else None

    def create_project(self, values: dict[str, Any]) -> Project:
        # organisation_id and created_by are filled in by the database from the caller.
        try:
            row = self._rest.insert("projects", values)
        except DatabaseError as exc:
            # A signed-in user without a profile has no organisation to put a project
            # in, so the database refuses the row. Say so, instead of a bare "forbidden".
            if (
                exc.pg_code in (_INSUFFICIENT_PRIVILEGE, _NOT_NULL_VIOLATION)
                and not self._has_profile()
            ):
                raise errors.forbidden(NO_PROFILE_MESSAGE) from exc
            raise _friendly_project_error(exc) from exc
        return Project.model_validate(row)

    def update_project(self, project_id: UUID, changes: dict[str, Any]) -> Project | None:
        try:
            rows = self._rest.update("projects", {"id": f"eq.{project_id}"}, changes)
        except DatabaseError as exc:
            raise _friendly_project_error(exc) from exc
        return Project.model_validate(rows[0]) if rows else None


def _friendly_project_error(exc: DatabaseError) -> Exception:
    for constraint, (field, message) in _PROJECT_CONSTRAINTS.items():
        if constraint in exc.pg_message:
            return errors.validation_error(message, field=field)
    return exc
