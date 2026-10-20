"""Open a finished workflow in Studio (spec 2026-10-20 workflow to Studio, section 3.1)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import ValidationError

from thoth_control_plane.api.dependencies import current_actor
from thoth_control_plane.application.edit_documents import (
    IDEMPOTENCY_KEY_ADAPTER,
    EditorUnavailable,
)
from thoth_control_plane.application.ports import StudioImportConflict
from thoth_control_plane.application.workflow_studio_imports import (
    ContentSetInvalid,
    ContentSetUnavailable,
    WorkflowInOtherProject,
    WorkflowStudioImportService,
    WorkflowStudioUnavailable,
)
from thoth_control_plane.application.workflows import WorkflowNotFound
from thoth_control_plane.domain.models import Actor
from thoth_control_plane.domain.studio_imports import StudioSourceInspection, WorkflowStudioImport

router = APIRouter()
PATH = "/projects/{project_id}/workflows/{workflow_id}/studio-import"
#: Each refusal and its fixed code, in the `{detail: {code}}` shape the Studio import routes use.
REFUSALS: tuple[tuple[type[Exception], int, str | None], ...] = (
    (WorkflowNotFound, status.HTTP_404_NOT_FOUND, None),
    (WorkflowInOtherProject, status.HTTP_409_CONFLICT, "workflow_in_other_project"),
    (ContentSetUnavailable, status.HTTP_409_CONFLICT, "content_set_unavailable"),
    (ContentSetInvalid, status.HTTP_409_CONFLICT, "content_set_invalid"),
    (StudioImportConflict, status.HTTP_409_CONFLICT, "studio_import_conflict"),
    (WorkflowStudioUnavailable, status.HTTP_503_SERVICE_UNAVAILABLE, None),
    (EditorUnavailable, status.HTTP_503_SERVICE_UNAVAILABLE, None),
)


def get_workflow_studio_service(request: Request) -> WorkflowStudioImportService:
    return request.app.state.workflow_studio_service


def _refused(error: Exception) -> HTTPException | None:
    for kind, code_status, code in REFUSALS:
        if isinstance(error, kind):
            return HTTPException(status_code=code_status, detail={"code": code} if code else None)
    return None


@router.get(PATH, response_model=StudioSourceInspection)
async def inspect_workflow_studio_import(
    project_id: str,
    workflow_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    service: Annotated[WorkflowStudioImportService, Depends(get_workflow_studio_service)],
) -> StudioSourceInspection:
    """Read-only: what opening this run would import, and the drafts already made from it."""
    try:
        return await service.inspect(project_id, workflow_id, actor)
    except Exception as error:
        refusal = _refused(error)
        if refusal is None:
            raise
        raise refusal from error


@router.post(PATH, response_model=WorkflowStudioImport, status_code=status.HTTP_201_CREATED)
async def open_workflow_in_studio(
    project_id: str,
    workflow_id: str,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    actor: Annotated[Actor, Depends(current_actor)],
    service: Annotated[WorkflowStudioImportService, Depends(get_workflow_studio_service)],
) -> WorkflowStudioImport:
    """Create (or replay) one draft from the run and bring its media in; a replay finishes the
    items an earlier attempt left unresolved."""
    try:
        IDEMPOTENCY_KEY_ADAPTER.validate_python(idempotency_key)
    except ValidationError as error:
        # The key itself is never echoed back: it may carry caller-controlled text.
        raise HTTPException(status_code=422, detail={"code": "invalid_idempotency_key"}) from error
    try:
        return await service.open(project_id, workflow_id, actor, idempotency_key)
    except Exception as error:
        refusal = _refused(error)
        if refusal is None:
            raise
        raise refusal from error
