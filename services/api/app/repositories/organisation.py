"""Data access for organisation members and invitations.

SupabaseOrganisationRepository acts as the signed-in user, so Row Level
Security limits every query: members see their own organisation's members, and
only an owner can see, create or revoke invitations.
"""

from typing import Any, Protocol
from uuid import UUID

from app.core import errors
from app.db.supabase import DatabaseError, SupabaseRest
from app.schemas.organisation import Invitation, InvitationPreview, Member
from app.schemas.platform import Role

# Everything except token_hash, which signed-in users are not allowed to read.
_INVITATION_COLUMNS = "id,email,role,invited_by,expires_at,accepted_at,created_at"
_MEMBER_COLUMNS = "id,email,full_name,role,created_at"

ALREADY_INVITED_MESSAGE = (
    "This person has already been invited. Revoke that invitation to send a new one."
)

_UNIQUE_VIOLATION = "23505"
_CHECK_VIOLATION = "23514"


class OrganisationRepository(Protocol):
    def my_role(self) -> Role | None: ...

    def list_members(self) -> list[Member]: ...

    def list_invitations(self) -> list[Invitation]: ...

    def create_invitation(self, email: str, token_hash: str) -> Invitation: ...

    def delete_open_invitation(self, invitation_id: UUID) -> bool: ...


class InvitationLookup(Protocol):
    def preview(self, code: str) -> InvitationPreview | None: ...


class SupabaseOrganisationRepository:
    def __init__(self, rest: SupabaseRest, user_id: UUID) -> None:
        self._rest = rest
        self._user_id = user_id

    def my_role(self) -> Role | None:
        rows = self._rest.select("profiles", {"id": f"eq.{self._user_id}"}, columns="role")
        return rows[0]["role"] if rows else None

    def list_members(self) -> list[Member]:
        # Row Level Security returns only the caller's organisation.
        rows = self._rest.select(
            "profiles", columns=_MEMBER_COLUMNS, order="created_at.asc,id.asc", limit=500
        )
        return [Member.model_validate(row) for row in rows]

    def list_invitations(self) -> list[Invitation]:
        rows = self._rest.select(
            "organisation_invitations",
            columns=_INVITATION_COLUMNS,
            order="created_at.desc,id.asc",
            limit=200,
        )
        return [Invitation.model_validate(row) for row in rows]

    def create_invitation(self, email: str, token_hash: str) -> Invitation:
        # organisation_id, invited_by, role and expires_at are filled in by the database.
        try:
            row = self._rest.insert(
                "organisation_invitations",
                {"email": email, "token_hash": token_hash},
                columns=_INVITATION_COLUMNS,
            )
        except DatabaseError as exc:
            if exc.pg_code == _UNIQUE_VIOLATION:
                raise errors.conflict(ALREADY_INVITED_MESSAGE) from exc
            if exc.pg_code == _CHECK_VIOLATION:
                raise errors.validation_error("Enter a valid email address", field="email") from exc
            raise
        return Invitation.model_validate(row)

    def delete_open_invitation(self, invitation_id: UUID) -> bool:
        deleted: list[dict[str, Any]] = self._rest.delete(
            "organisation_invitations", {"id": f"eq.{invitation_id}", "select": "id"}
        )
        return bool(deleted)


class SupabaseInvitationLookup:
    """Reads the preview of an invite link as a signed-out caller. The database
    function behind it answers only for a code that is still open."""

    def __init__(self, rest: SupabaseRest) -> None:
        self._rest = rest

    def preview(self, code: str) -> InvitationPreview | None:
        rows = self._rest.rpc("invitation_preview", {"p_code": code})
        return InvitationPreview.model_validate(rows[0]) if rows else None
