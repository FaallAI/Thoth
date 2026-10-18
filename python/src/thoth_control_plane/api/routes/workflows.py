"""Versioned workflow lifecycle routes."""

import asyncio
import re
from collections.abc import AsyncIterator
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import FileResponse, Response, StreamingResponse

from thoth_control_plane.api.dependencies import current_actor
from thoth_control_plane.api.ranged import ranged_response
from thoth_control_plane.api.routes.workflow_runs import get_run_service
from thoth_control_plane.application import (
    Actor,
    ApprovalSubmission,
    ArtifactNotFound,
    RetryRequest,
    StylePreset,
    WorkflowEvent,
    WorkflowRequest,
    WorkflowService,
    WorkflowSummary,
)
from thoth_control_plane.application.workflow_runs import WorkflowRunService
from thoth_control_plane.infrastructure.media_store import (
    MediaLocatorInvalid,
    MediaStoreUnavailable,
    MediaUnavailable,
)
from thoth_control_plane.infrastructure.report_store import REPORT_KINDS, ReportStoreUnavailable

router = APIRouter()


def get_workflow_service(request: Request) -> WorkflowService:
    return request.app.state.workflow_service


@router.get("/style-presets", response_model=list[StylePreset])
async def list_style_presets(
    actor: Annotated[Actor, Depends(current_actor)],
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> list[StylePreset]:
    return await service.list_style_presets(actor=actor)


@router.post(
    "/workflows",
    response_model=WorkflowSummary,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_workflow(
    request: WorkflowRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    actor: Annotated[Actor, Depends(current_actor)],
    runs: Annotated[WorkflowRunService, Depends(get_run_service)],
) -> WorkflowSummary:
    return await runs.start(None, request, actor=actor, idempotency_key=idempotency_key)


@router.get("/workflows/{workflow_id}", response_model=WorkflowSummary)
async def get_workflow(
    workflow_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    runs: Annotated[WorkflowRunService, Depends(get_run_service)],
) -> WorkflowSummary:
    return await runs.get(workflow_id, actor=actor)


@router.get(
    "/workflows/{workflow_id}/artifacts/{artifact_id}",
    response_class=FileResponse,
    responses={
        status.HTTP_200_OK: {
            "content": {
                "application/json": {"schema": {}},
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
            },
        }
    },
)
async def download_workflow_artifact(
    workflow_id: str,
    artifact_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(current_actor)],
    runs: Annotated[WorkflowRunService, Depends(get_run_service)],
) -> Response:
    """Authorize through the workflow owner boundary, then serve one safe artifact."""

    artifact = await runs.get_artifact(workflow_id, artifact_id, actor=actor)
    if artifact.kind in REPORT_KINDS:
        reports = request.app.state.report_store
        try:
            if reports is None:
                raise ReportStoreUnavailable("report_store_unavailable")
            content = await asyncio.to_thread(reports.get, artifact.location)
        except ReportStoreUnavailable as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="report_store_unavailable",
            ) from error
        if content is None:
            raise ArtifactNotFound
        return Response(
            content,
            media_type=artifact.media_type,
            headers={"Content-Disposition": f'attachment; filename="{artifact.artifact_id}.json"'},
        )
    # Workflow media lives in the media store since PR #19; no service mounts the volume.
    media = request.app.state.media_store
    try:
        size = await asyncio.to_thread(media.size, artifact.location)
    except (MediaUnavailable, MediaLocatorInvalid):
        raise ArtifactNotFound from None
    except MediaStoreUnavailable as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="media_store_unavailable"
        ) from error
    suffix = PurePosixPath(artifact.location).suffix
    return ranged_response(
        size=size,
        read=lambda start, end: media.open_range(artifact.location, start, end),
        media_type=artifact.media_type,
        range_header=request.headers.get("range"),
        headers={"Content-Disposition": f'attachment; filename="{artifact.artifact_id}{suffix}"'},
    )


@router.get(
    "/workflows/{workflow_id}/events",
    response_model=WorkflowEvent,
    response_class=StreamingResponse,
    responses={
        status.HTTP_200_OK: {
            "content": {
                "text/event-stream": {"schema": {"$ref": "#/components/schemas/WorkflowEvent"}}
            }
        }
    },
)
async def stream_workflow_events(
    workflow_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    """Stream the current workflow snapshot and replay only unseen typed events."""
    after_sequence = _parse_last_event_id(last_event_id)

    async def encoded_events() -> AsyncIterator[str]:
        if last_event_id is None:
            snapshot = _workflow_snapshot_event(
                await service.get(workflow_id, actor=actor), sequence=1
            )
            yield f"event: workflow.snapshot\ndata: {snapshot.model_dump_json()}\n\n"
        async for event in service.stream_events(
            workflow_id,
            actor=actor,
            after_sequence=after_sequence,
        ):
            yield (
                f"id: {event.sequence}\nevent: {event.kind}\ndata: {event.model_dump_json()}\n\n"
            )

    return StreamingResponse(encoded_events(), media_type="text/event-stream")


def _parse_last_event_id(value: str | None) -> int:
    if value is None:
        return 0
    if not re.fullmatch(r"[0-9]+", value):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Last-Event-ID must be a non-negative integer",
        )
    return int(value)


def _workflow_snapshot_event(summary: WorkflowSummary, *, sequence: int) -> WorkflowEvent:
    """Represent an otherwise eventless current state with the typed event contract."""
    kind_by_status = {
        "queued": "workflow.queued",
        "running": "workflow.started",
        "awaiting_approval": "approval.required",
        "succeeded": "workflow.completed",
        "failed": "workflow.failed",
        "cancelled": "workflow.cancelled",
    }
    return WorkflowEvent(
        workflow_id=summary.workflow_id,
        event_id=f"snapshot_{summary.workflow_id}",
        sequence=max(1, sequence),
        kind=kind_by_status[str(summary.status)],
        occurred_at=summary.updated_at,
    )


@router.post("/workflows/{workflow_id}/cancel", response_model=WorkflowSummary)
async def cancel_workflow(
    workflow_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> WorkflowSummary:
    return await service.cancel(workflow_id, actor=actor)


@router.post("/workflows/{workflow_id}/retry", response_model=WorkflowSummary)
async def retry_workflow(
    workflow_id: str,
    retry: RetryRequest,
    actor: Annotated[Actor, Depends(current_actor)],
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> WorkflowSummary:
    return await service.retry(workflow_id, from_stage=retry.from_stage, actor=actor)


@router.post("/workflows/{workflow_id}/approve", response_model=WorkflowSummary)
async def approve_workflow(
    workflow_id: str,
    approval: ApprovalSubmission,
    actor: Annotated[Actor, Depends(current_actor)],
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> WorkflowSummary:
    return await service.record_approval(workflow_id, approval, actor=actor)
