"""Request and response shapes for the platform endpoints (F01, F02).

Field names and rules match docs/api-contracts.md and docs/database-schema.md.
Input models ignore unknown fields, so a client that sends organisation_id,
created_by or status cannot set them.
"""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, StringConstraints, model_validator

Role = Literal["owner", "member"]
ProjectStatus = Literal["active", "archived"]

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Address = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class Organisation(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime


class Profile(BaseModel):
    id: UUID
    organisation_id: UUID
    email: str
    full_name: str
    role: Role
    created_at: datetime
    updated_at: datetime


class Me(BaseModel):
    profile: Profile
    organisation: Organisation


class MeUpdate(BaseModel):
    full_name: Name


class Project(BaseModel):
    id: UUID
    organisation_id: UUID
    name: str
    client_name: str
    site_address: str
    status: ProjectStatus
    start_date: date | None
    end_date: date | None
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime


class ProjectList(BaseModel):
    items: list[Project]


def _check_date_order(start: date | None, end: date | None) -> None:
    if start is not None and end is not None and end < start:
        raise ValueError("End date must not be before start date")


class ProjectCreate(BaseModel):
    name: Name
    client_name: Name
    site_address: Address = ""
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def _dates_in_order(self) -> "ProjectCreate":
        _check_date_order(self.start_date, self.end_date)
        return self


class ProjectUpdate(BaseModel):
    """PATCH body: only the fields that are sent are changed."""

    name: Name | None = None
    client_name: Name | None = None
    site_address: Address | None = None
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def _validate(self) -> "ProjectUpdate":
        sent = self.model_fields_set
        if not sent:
            raise ValueError("Send at least one field to update")
        for field in ("name", "client_name", "site_address"):
            if field in sent and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        # When both dates are sent they can be checked here; when only one is,
        # the database constraint compares it with the stored value.
        _check_date_order(self.start_date, self.end_date)
        return self

    def changes(self) -> dict:
        """The fields the client actually sent, ready to store."""
        return self.model_dump(exclude_unset=True, mode="json")
