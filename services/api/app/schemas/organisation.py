"""Request and response shapes for organisation members and invitations (F01).

Field names match the database columns in docs/database-schema.md.
"""

import re
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, computed_field, field_validator

from app.schemas.platform import Role

InvitationStatus = Literal["pending", "accepted", "expired"]

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Member(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: Role
    created_at: datetime


class MemberList(BaseModel):
    items: list[Member]


class Invitation(BaseModel):
    id: UUID
    email: str
    role: Role
    invited_by: UUID | None
    expires_at: datetime
    accepted_at: datetime | None
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> InvitationStatus:
        if self.accepted_at is not None:
            return "accepted"
        return "expired" if self.expires_at <= datetime.now(timezone.utc) else "pending"


class InvitationList(BaseModel):
    items: list[Invitation]


class InvitationCreated(Invitation):
    # The secret that goes in the invite link. Returned once, when the invitation
    # is created, and never again: only its hash is stored.
    invite_code: str


class InvitationCreate(BaseModel):
    email: str

    @field_validator("email", mode="after")
    @classmethod
    def _tidy(cls, value: str) -> str:
        value = value.strip().lower()
        if len(value) > 320 or not _EMAIL.match(value):
            raise ValueError("Enter a valid email address")
        return value


class InvitationPreview(BaseModel):
    """What a signed-out person sees when they open an invite link."""

    organisation_name: str
    email: str
    expires_at: datetime
