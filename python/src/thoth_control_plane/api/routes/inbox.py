"""The inbox: approvals, unacknowledged failures, and admin-only accounts (spec G5)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from thoth_control_plane.api.dependencies import current_actor, current_principal
from thoth_control_plane.api.routes.workflow_runs import get_run_service
from thoth_control_plane.application.workflow_runs import WorkflowRunService
from thoth_control_plane.auth.models import Principal, is_platform_admin
from thoth_control_plane.domain import Actor
from thoth_control_plane.domain.workflow_runs import Inbox

router = APIRouter()


@router.get("/inbox", response_model=Inbox)
async def read_inbox(
    request: Request,
    actor: Annotated[Actor, Depends(current_actor)],
    principal: Annotated[Principal, Depends(current_principal)],
    runs: Annotated[WorkflowRunService, Depends(get_run_service)],
) -> Inbox:
    """The caller's workspace attention list. The account section follows the
    `platform_actor` rule: a platform admin holding the admin scope."""
    state = request.app.state
    return await runs.inbox(
        actor=actor,
        platform_admin=is_platform_admin(principal) and "admin" in principal.scopes,
        accounts=getattr(state, "source_account_store", None),
    )
