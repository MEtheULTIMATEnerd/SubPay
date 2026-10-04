"""Project management (F02).

A project in another organisation is indistinguishable from one that does not
exist: both are a 404.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import Platform
from app.core import errors
from app.schemas.platform import Project, ProjectCreate, ProjectList, ProjectStatus, ProjectUpdate

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=ProjectList, summary="List your organisation's projects")
def list_projects(
    platform: Platform,
    status_filter: Annotated[ProjectStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProjectList:
    projects = platform.list_projects(status=status_filter, limit=limit, offset=offset)
    return ProjectList(items=projects)


@router.post(
    "",
    response_model=Project,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project",
)
def create_project(body: ProjectCreate, platform: Platform) -> Project:
    return platform.create_project(body.model_dump(mode="json"))


@router.get("/{project_id}", response_model=Project, summary="Get one project")
def get_project(project_id: UUID, platform: Platform) -> Project:
    project = platform.get_project(project_id)
    if project is None:
        raise errors.not_found("Project")
    return project


@router.patch("/{project_id}", response_model=Project, summary="Edit a project")
def update_project(project_id: UUID, body: ProjectUpdate, platform: Platform) -> Project:
    project = platform.update_project(project_id, body.changes())
    if project is None:
        raise errors.not_found("Project")
    return project


@router.post("/{project_id}/archive", response_model=Project, summary="Archive a project")
def archive_project(project_id: UUID, platform: Platform) -> Project:
    project = platform.update_project(project_id, {"status": "archived"})
    if project is None:
        raise errors.not_found("Project")
    return project


@router.post("/{project_id}/restore", response_model=Project, summary="Restore a project")
def restore_project(project_id: UUID, platform: Platform) -> Project:
    project = platform.update_project(project_id, {"status": "active"})
    if project is None:
        raise errors.not_found("Project")
    return project
