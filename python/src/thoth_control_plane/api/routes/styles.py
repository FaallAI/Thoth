"""Style templates and applying one to a draft (spec 2026-11-10)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from thoth_control_plane.api.dependencies import current_actor, current_principal
from thoth_control_plane.api.routes.edit_documents import _refused, _revision_conflict
from thoth_control_plane.application.edit_documents import (
    EditDocumentNotFound,
    EditDocumentRefused,
    EditorUnavailable,
    RestoreRevisionRequest,
)
from thoth_control_plane.application.ports import EditDocumentRevisionConflict
from thoth_control_plane.application.styles import (
    AppliedStyleResult,
    ApplyStyleRequest,
    StyleNotFound,
    StyleRefused,
    StyleService,
    StyleSummary,
)
from thoth_control_plane.auth.models import Principal
from thoth_control_plane.domain import Actor, EditDocument
from thoth_control_plane.domain.edit_document_v2 import DocumentRevisionConflictBody

router = APIRouter()


def get_style_service(request: Request) -> StyleService:
    state = request.app.state

    async def roles(project_id: str, document_id: str) -> dict[str, str]:
        # A draft made in Studio has no import: its clips name their beats themselves.
        try:
            inventory = await state.studio_import_service.get_inventory(project_id, document_id)
        except Exception:
            return {}
        return {item.item_id: item.role for item in inventory.items if item.role}

    return StyleService(
        templates=state.style_templates,
        documents=state.edit_document_service,
        narrations=getattr(state, "narration_service", None),
        roles=roles,
    )


Service = Annotated[StyleService, Depends(get_style_service)]
Caller = Annotated[Principal, Depends(current_principal)]

CONFLICT = {status.HTTP_409_CONFLICT: {"model": DocumentRevisionConflictBody}}


def _style_refused(error: StyleRefused) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": error.code})


@router.get("/projects/{project_id}/styles", response_model=list[StyleSummary])
async def list_styles(
    project_id: str,
    _: Annotated[Actor, Depends(current_actor)],
    principal: Caller,
    service: Service,
) -> list[StyleSummary]:
    return await service.list(principal.workspace_id)


@router.post(
    "/projects/{project_id}/edit-documents/{document_id}/style",
    response_model=AppliedStyleResult,
    responses=CONFLICT,
)
async def apply_style(
    project_id: str,
    document_id: str,
    payload: ApplyStyleRequest,
    _: Annotated[Actor, Depends(current_actor)],
    principal: Caller,
    service: Service,
) -> AppliedStyleResult | JSONResponse:
    try:
        return await service.apply(principal.workspace_id, project_id, document_id, payload)
    except StyleRefused as error:
        raise _style_refused(error) from error
    except (StyleNotFound, EditDocumentNotFound) as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    except EditDocumentRevisionConflict as error:
        return _revision_conflict(error)
    except EditDocumentRefused as error:
        raise _refused() from error
    except EditorUnavailable as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from error


@router.post(
    "/projects/{project_id}/edit-documents/{document_id}/style/undo",
    response_model=EditDocument,
    responses=CONFLICT,
)
async def undo_style(
    project_id: str,
    document_id: str,
    payload: RestoreRevisionRequest,
    _: Annotated[Actor, Depends(current_actor)],
    service: Service,
) -> EditDocument | JSONResponse:
    try:
        return await service.undo(project_id, document_id, payload)
    except StyleRefused as error:
        raise _style_refused(error) from error
    except EditDocumentNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    except EditDocumentRevisionConflict as error:
        return _revision_conflict(error)
    except EditDocumentRefused as error:
        raise _refused() from error
    except EditorUnavailable as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from error
