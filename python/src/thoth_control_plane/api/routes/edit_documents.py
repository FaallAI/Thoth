"""Authenticated Creator Studio import and immutable-document retrieval routes."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from thoth_control_plane.api.dependencies import current_actor
from thoth_control_plane.application.edit_documents import (
    ContentSetImportRequest,
    EditDocumentNotFound,
    EditDocumentService,
    EditorUnavailable,
    UpgradeTimelineRequest,
)
from thoth_control_plane.application.ports import (
    EditDocumentRevisionConflict,
    EditDocumentUpgradeConflict,
)
from thoth_control_plane.application.prompt_proposal_ports import PromptProposalStoreUnavailable
from thoth_control_plane.application.story_assist import (
    StoryAssistInvalidOutput,
    StoryAssistNotConfigured,
    StoryAssistNoText,
    StoryAssistService,
    StoryAssistUnavailable,
)
from thoth_control_plane.domain import Actor, EditDocument
from thoth_control_plane.domain.edit_document_list import EditDocumentListPage
from thoth_control_plane.domain.edit_document_operations import EditDocumentPatch
from thoth_control_plane.domain.edit_document_v2 import DocumentRevisionConflictBody
from thoth_control_plane.domain.story_assist import StoryAssistProposal, StoryAssistRequest

router = APIRouter()
logger = logging.getLogger(__name__)


def get_edit_document_service(request: Request) -> EditDocumentService:
    return request.app.state.edit_document_service


@router.post(
    "/projects/{project_id}/edit-documents/import-content-set",
    response_model=EditDocument,
    status_code=status.HTTP_201_CREATED,
)
async def import_content_set(
    project_id: str,
    payload: ContentSetImportRequest,
    _: Annotated[Actor, Depends(current_actor)],
    service: Annotated[EditDocumentService, Depends(get_edit_document_service)],
) -> EditDocument:
    try:
        return await service.import_content_set(project_id, payload)
    except EditorUnavailable as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from error


@router.get("/projects/{project_id}/edit-documents", response_model=EditDocumentListPage)
async def list_edit_documents(
    project_id: str,
    request: Request,
    _: Annotated[Actor, Depends(current_actor)],
    service: Annotated[EditDocumentService, Depends(get_edit_document_service)],
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> EditDocumentListPage:
    try:
        page = await service.list_documents(project_id, limit=limit, cursor=cursor)
    except EditorUnavailable as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from error
    return await _with_source_runs(request, project_id, page)


async def _with_source_runs(
    request: Request, project_id: str, page: EditDocumentListPage
) -> EditDocumentListPage:
    """Restyle B9: each draft's source run, when that run still lives in this project.

    Read from the run rows on every call, never stored with the draft; a missing store or
    a failed read leaves the source out rather than failing the list.
    """
    runs = getattr(request.app.state, "workflow_run_store", None)
    wanted = {item.source_workflow_id for item in page.items if item.source_workflow_id}
    if runs is None or not wanted:
        return page
    try:
        # A run nobody has listed since B2 shipped has not read its title yet.
        await asyncio.to_thread(runs.fill_listing, sorted(wanted))
        found = {
            workflow_id: await asyncio.to_thread(runs.get, workflow_id) for workflow_id in wanted
        }
    except Exception:
        logger.warning("documents list: source runs unavailable", exc_info=True)
        return page
    items = []
    for item in page.items:
        run = found.get(item.source_workflow_id or "")
        if run is not None and run.project_id == project_id:
            item = item.model_copy(
                update={
                    "source_platform": run.platform,
                    "source_title": run.title or None,
                    "source_owner_handle": run.owner_handle,
                    "source_has_post_card": bool(run.post_card_location),
                }
            )
        items.append(item)
    return page.model_copy(update={"items": items})


@router.get("/projects/{project_id}/edit-documents/{document_id}", response_model=EditDocument)
async def get_edit_document(
    project_id: str,
    document_id: str,
    _: Annotated[Actor, Depends(current_actor)],
    service: Annotated[EditDocumentService, Depends(get_edit_document_service)],
) -> EditDocument:
    try:
        return await service.get_latest(project_id, document_id)
    except EditDocumentNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    except EditorUnavailable as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from error


@router.patch(
    "/projects/{project_id}/edit-documents/{document_id}",
    response_model=EditDocument,
    responses={status.HTTP_409_CONFLICT: {"model": DocumentRevisionConflictBody}},
)
async def apply_edit_document_patch(
    project_id: str,
    document_id: str,
    patch: EditDocumentPatch,
    _: Annotated[Actor, Depends(current_actor)],
    service: Annotated[EditDocumentService, Depends(get_edit_document_service)],
    request: Request,
) -> EditDocument | JSONResponse:
    narration = getattr(request.app.state, "narration_service", None)
    # The narration writes the draft while it runs (spec 2026-10-31): edits wait for it.
    if narration is not None and await narration.is_locked(project_id, document_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail={"code": "narration_in_progress"}
        )
    try:
        return await service.apply_patch(project_id, document_id, patch)
    except EditDocumentNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    except EditDocumentRevisionConflict as error:
        return _revision_conflict(error)
    except EditorUnavailable as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from error


@router.post(
    "/projects/{project_id}/edit-documents/{document_id}/upgrade-timeline",
    response_model=EditDocument,
    responses={status.HTTP_409_CONFLICT: {"model": DocumentRevisionConflictBody}},
)
async def upgrade_edit_document_timeline(
    project_id: str,
    document_id: str,
    payload: UpgradeTimelineRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    _: Annotated[Actor, Depends(current_actor)],
    service: Annotated[EditDocumentService, Depends(get_edit_document_service)],
) -> EditDocument | JSONResponse:
    """Upgrade one document to schema version 2 under a caller-supplied replay key."""
    if not idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "missing_idempotency_key"},
        )
    try:
        return await service.upgrade_to_timeline(project_id, document_id, payload, idempotency_key)
    except ValidationError as error:
        # The key itself is never echoed back: it may carry caller-controlled text.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_idempotency_key"},
        ) from error
    except EditDocumentNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    except EditDocumentRevisionConflict as error:
        return _revision_conflict(error)
    except EditDocumentUpgradeConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail={"code": "document_upgrade_conflict"}
        ) from error
    except EditorUnavailable as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from error


def get_story_assist_service(request: Request) -> StoryAssistService:
    return request.app.state.story_assist_service


#: Each Assist refusal and the code the editor explains it with (spec 2026-10-27, 7).
ASSIST_REFUSALS: tuple[tuple[type[Exception] | tuple[type[Exception], ...], int, str], ...] = (
    (StoryAssistNotConfigured, status.HTTP_409_CONFLICT, "assist_not_configured"),
    (StoryAssistNoText, status.HTTP_422_UNPROCESSABLE_ENTITY, "assist_no_text"),
    (StoryAssistInvalidOutput, status.HTTP_422_UNPROCESSABLE_ENTITY, "assist_invalid_output"),
    (
        (StoryAssistUnavailable, EditorUnavailable, PromptProposalStoreUnavailable),
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "assist_unavailable",
    ),
)


@router.post(
    "/projects/{project_id}/edit-documents/{document_id}/assist",
    response_model=StoryAssistProposal,
    responses={status.HTTP_409_CONFLICT: {"model": DocumentRevisionConflictBody}},
)
async def propose_story_assist(
    project_id: str,
    document_id: str,
    request: StoryAssistRequest,
    _: Annotated[Actor, Depends(current_actor)],
    service: Annotated[StoryAssistService, Depends(get_story_assist_service)],
) -> StoryAssistProposal | JSONResponse:
    """One text proposal for a beat; nothing changes until the editor applies it."""
    try:
        return await service.propose(project_id, document_id, request)
    except EditDocumentNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    except EditDocumentRevisionConflict as error:
        return _revision_conflict(error)
    except Exception as error:
        for kind, code_status, code in ASSIST_REFUSALS:
            if isinstance(error, kind):
                raise HTTPException(status_code=code_status, detail={"code": code}) from error
        raise


def _revision_conflict(error: EditDocumentRevisionConflict) -> JSONResponse:
    body = DocumentRevisionConflictBody(latest=error.latest)
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=body.model_dump(mode="json"))
