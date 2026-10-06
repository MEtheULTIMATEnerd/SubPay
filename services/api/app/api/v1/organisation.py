"""Organisation members and invitations (F01).

An owner invites a person by email and gets a one-time invite link to pass on.
Signing up through that link joins the owner's organisation as a member.
"""

import hashlib
import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Response, status

from app.api.deps import InvitationPreviews, OrganisationData
from app.core import errors
from app.repositories.organisation import OrganisationRepository
from app.repositories.platform import NO_PROFILE_MESSAGE
from app.schemas.organisation import (
    InvitationCreate,
    InvitationCreated,
    InvitationList,
    InvitationPreview,
    MemberList,
)

router = APIRouter(tags=["organisation"])

OWNER_ONLY_MESSAGE = "Only an owner can manage invitations"


def hash_invite_code(code: str) -> str:
    """What is stored for an invite code. Must match the database's sha256 of the code."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _require_owner(organisation: OrganisationRepository) -> None:
    """A clear answer for non-owners. Row Level Security enforces the same rule."""
    role = organisation.my_role()
    if role is None:
        raise errors.forbidden(NO_PROFILE_MESSAGE)
    if role != "owner":
        raise errors.forbidden(OWNER_ONLY_MESSAGE)


@router.get(
    "/organisation/members",
    response_model=MemberList,
    summary="List the members of your organisation",
)
def list_members(organisation: OrganisationData) -> MemberList:
    return MemberList(items=organisation.list_members())


@router.get(
    "/organisation/invitations",
    response_model=InvitationList,
    summary="List your organisation's invitations (owners only)",
)
def list_invitations(organisation: OrganisationData) -> InvitationList:
    _require_owner(organisation)
    return InvitationList(items=organisation.list_invitations())


@router.post(
    "/organisation/invitations",
    response_model=InvitationCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a person to your organisation (owners only)",
)
def create_invitation(body: InvitationCreate, organisation: OrganisationData) -> InvitationCreated:
    """Returns `invite_code` once. Put it in a link: `/signup?invite=<invite_code>`."""
    _require_owner(organisation)
    if any(member.email.lower() == body.email for member in organisation.list_members()):
        raise errors.conflict("This person is already a member of your organisation")

    code = secrets.token_urlsafe(32)
    invitation = organisation.create_invitation(body.email, hash_invite_code(code))
    return InvitationCreated(**invitation.model_dump(exclude={"status"}), invite_code=code)


@router.delete(
    "/organisation/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an invitation that has not been accepted (owners only)",
)
def revoke_invitation(invitation_id: UUID, organisation: OrganisationData) -> Response:
    _require_owner(organisation)
    if not organisation.delete_open_invitation(invitation_id):
        raise errors.not_found("Invitation")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/invitations/{invite_code}",
    response_model=InvitationPreview,
    summary="Look up an invite link (no sign-in needed)",
)
def preview_invitation(
    invite_code: Annotated[str, Path(min_length=20, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")],
    invitations: InvitationPreviews,
) -> InvitationPreview:
    """Used by the sign-up page. A wrong, used, revoked or expired code is a 404."""
    preview = invitations.preview(invite_code)
    if preview is None:
        raise errors.not_found("Invitation")
    return preview
