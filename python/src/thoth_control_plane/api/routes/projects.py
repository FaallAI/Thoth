"""Projects owned by the control plane (spec 2026-10-18, section 3.2)."""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from thoth_control_plane.api.dependencies import current_actor
from thoth_control_plane.application import Actor
from thoth_control_plane.auth.models import actor_workspace_id
from thoth_control_plane.domain.projects import CreateProject, Project, ProjectList
from thoth_control_plane.infrastructure.project_store import ProjectStoreUnavailable

router = APIRouter()


def get_project_store(request: Request) -> Any:
    store = request.app.state.project_store
    if store is None:
        raise ProjectStoreUnavailable("project_store_unavailable")
    return store


@router.get("/projects", response_model=ProjectList)
async def list_projects(
    actor: Annotated[Actor, Depends(current_actor)],
    store: Annotated[Any, Depends(get_project_store)],
) -> ProjectList:
    return ProjectList(
        items=await asyncio.to_thread(store.list, actor_workspace_id(actor.actor_id))
    )


@router.post("/projects", response_model=Project, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: CreateProject,
    actor: Annotated[Actor, Depends(current_actor)],
    store: Annotated[Any, Depends(get_project_store)],
) -> Project:
    return await asyncio.to_thread(store.create, body.name, actor_workspace_id(actor.actor_id))


@router.get("/projects/{project_id}", response_model=Project)
async def get_project(
    project_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    store: Annotated[Any, Depends(get_project_store)],
) -> Project:
    project = await asyncio.to_thread(store.get, project_id, actor_workspace_id(actor.actor_id))
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project_not_found")
    return project
