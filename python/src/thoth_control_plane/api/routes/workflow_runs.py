"""Workflow runs per project: start, list, move (spec 2026-10-18, section 3.3)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status

from thoth_control_plane.api.dependencies import current_actor
from thoth_control_plane.application import Actor, WorkflowRequest, WorkflowSummary
from thoth_control_plane.application.workflow_runs import WorkflowRunService
from thoth_control_plane.domain.workflow_runs import MoveWorkflow, WorkflowRun, WorkflowRunPage

router = APIRouter()

Limit = Annotated[int, Query(ge=1, le=50)]


def get_run_service(request: Request) -> WorkflowRunService:
    state = request.app.state
    return WorkflowRunService(
        state.workflow_run_store,
        state.project_store,
        state.workflow_service,
        state.workflow_gateway,
    )


@router.post(
    "/projects/{project_id}/workflows",
    response_model=WorkflowSummary,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_project_workflow(
    project_id: str,
    request: WorkflowRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    actor: Annotated[Actor, Depends(current_actor)],
    runs: Annotated[WorkflowRunService, Depends(get_run_service)],
) -> WorkflowSummary:
    return await runs.start(project_id, request, actor=actor, idempotency_key=idempotency_key)


@router.get("/projects/{project_id}/workflows", response_model=WorkflowRunPage)
async def list_project_workflows(
    project_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    runs: Annotated[WorkflowRunService, Depends(get_run_service)],
    cursor: str | None = None,
    limit: Limit = 20,
) -> WorkflowRunPage:
    return await runs.page(
        project_id=project_id, unassigned=False, actor=actor, cursor=cursor, limit=limit
    )


@router.get("/workflows", response_model=WorkflowRunPage)
async def list_unassigned_workflows(
    actor: Annotated[Actor, Depends(current_actor)],
    runs: Annotated[WorkflowRunService, Depends(get_run_service)],
    unassigned: Annotated[bool, Query()],
    cursor: str | None = None,
    limit: Limit = 20,
) -> WorkflowRunPage:
    if not unassigned:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="unassigned_must_be_true"
        )
    return await runs.page(
        project_id=None, unassigned=True, actor=actor, cursor=cursor, limit=limit
    )


@router.patch("/workflows/{workflow_id}", response_model=WorkflowRun)
async def move_workflow(
    workflow_id: str,
    body: MoveWorkflow,
    actor: Annotated[Actor, Depends(current_actor)],
    runs: Annotated[WorkflowRunService, Depends(get_run_service)],
) -> WorkflowRun:
    return await runs.assign(workflow_id, body.project_id, actor=actor)
