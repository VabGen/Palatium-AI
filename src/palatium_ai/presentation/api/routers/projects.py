# src/palatium_ai/presentation/api/routers/projects.py

"""API routes for durable Projects (P2 Pin / Projects)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from palatium_ai.core.types.pagination import PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MAX
from palatium_ai.domain.projects.errors import ProjectNotFoundError
from palatium_ai.domain.projects.models import ProjectRecord
from palatium_ai.presentation.resources import get_app_resources
from palatium_ai.presentation.security.deps import get_principal

router = APIRouter()


class ProjectResponse(BaseModel):
    """Public project row."""

    id: UUID
    user_id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(BaseModel):
    """Envelope for project collections."""

    items: list[ProjectResponse]
    limit: int
    offset: int
    count: int


class CreateProjectRequest(BaseModel):
    """Create a named project folder."""

    title: str = Field(min_length=1, max_length=255)


class RenameProjectRequest(BaseModel):
    """Rename an existing project."""

    title: str = Field(min_length=1, max_length=255)


@router.get("/", response_model=ProjectListResponse)
async def list_projects(
    request: Request,
    limit: int = Query(default=PAGE_LIMIT_DEFAULT, ge=1, le=PAGE_LIMIT_MAX),
    offset: int = Query(default=0, ge=0),
) -> ProjectListResponse:
    """List projects owned by the caller."""
    principal = get_principal(request)
    resources = get_app_resources(request.app)
    service = resources.project_service
    if service is None:
        raise HTTPException(status_code=503, detail="Projects service unavailable")
    items = await service.list_projects(
        user_id=principal.subject,
        limit=limit,
        offset=offset,
    )
    return ProjectListResponse(
        items=[_to_response(item) for item in items],
        limit=limit,
        offset=offset,
        count=len(items),
    )


@router.post("/", response_model=ProjectResponse, status_code=201)
async def create_project(body: CreateProjectRequest, request: Request) -> ProjectResponse:
    """Create a project owned by the JWT subject."""
    principal = get_principal(request)
    resources = get_app_resources(request.app)
    service = resources.project_service
    if service is None:
        raise HTTPException(status_code=503, detail="Projects service unavailable")
    try:
        project = await service.create(user_id=principal.subject, title=body.title)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_response(project)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def rename_project(
    project_id: UUID,
    body: RenameProjectRequest,
    request: Request,
) -> ProjectResponse:
    """Rename a project owned by the caller."""
    principal = get_principal(request)
    resources = get_app_resources(request.app)
    service = resources.project_service
    if service is None:
        raise HTTPException(status_code=503, detail="Projects service unavailable")
    try:
        project = await service.rename(
            user_id=principal.subject,
            project_id=project_id,
            title=body.title,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_response(project)


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: UUID, request: Request) -> None:
    """Delete a project owned by the caller."""
    principal = get_principal(request)
    resources = get_app_resources(request.app)
    service = resources.project_service
    if service is None:
        raise HTTPException(status_code=503, detail="Projects service unavailable")
    try:
        await service.delete(user_id=principal.subject, project_id=project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _to_response(project: ProjectRecord) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        user_id=project.user_id,
        title=project.title,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )
