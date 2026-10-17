"""The private half of the renderer protocol, hosted by the control plane.

These two routes exist only for the isolated renderer: they are excluded from
the public schema and the generated browser client, they accept only the shared
internal credential, and they carry no project scope because the renderer never
learns one. The renderer reads the bundle the control plane staged and reports
sequenced events; it can neither supply a document nor name a path.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from thoth_control_plane.api.dependencies import internal_renderer
from thoth_control_plane.api.routes.render_jobs import safe_render_errors
from thoth_control_plane.application.render_job_ports import RenderOutputTooLarge
from thoth_control_plane.application.render_jobs import RenderJobService
from thoth_control_plane.domain.models import OpaqueId, StrictModel
from thoth_control_plane.domain.render_jobs import (
    NonNegativeInt,
    RenderJobEvent,
    RenderStatus,
)

router = APIRouter(
    prefix="/internal/render-jobs",
    include_in_schema=False,
    dependencies=[Depends(internal_renderer)],
)


class RenderEventAck(StrictModel):
    """Authoritative state after one event, so the renderer needs no other read."""

    status: RenderStatus
    last_event_sequence: NonNegativeInt


def get_render_job_service(request: Request) -> RenderJobService:
    return request.app.state.render_job_service


ServiceDependency = Annotated[RenderJobService, Depends(get_render_job_service)]


@router.get("/{render_job_id}/bundle", include_in_schema=False)
async def read_render_bundle(render_job_id: OpaqueId, service: ServiceDependency) -> Response:
    """Serve the immutable bundle staged for exactly this job."""
    with safe_render_errors(unavailable=(status.HTTP_404_NOT_FOUND, "render_bundle_unavailable")):
        bundle = await service.bundle(render_job_id)
    return Response(content=bundle, media_type="application/json")


@router.get("/{render_job_id}/assets/{asset_id}", include_in_schema=False)
async def read_render_asset(
    render_job_id: OpaqueId, asset_id: OpaqueId, service: ServiceDependency
) -> Response:
    """Stream one asset the job's bundle lists, and nothing else."""
    with safe_render_errors(unavailable=(status.HTTP_404_NOT_FOUND, "render_asset_unavailable")):
        location = await service.asset_location(render_job_id, asset_id)
        size = await asyncio.to_thread(service.object_size, location)
    return StreamingResponse(
        service.read_object(location, 0, None),
        media_type="application/octet-stream",
        headers={"Content-Length": str(size)},
    )


class RenderOutputReceipt(StrictModel):
    """What the control plane measured of the renderer's upload."""

    size_bytes: NonNegativeInt
    checksum: str


@router.put("/{render_job_id}/output", include_in_schema=False)
async def receive_render_output(
    render_job_id: OpaqueId, request: Request, service: ServiceDependency
) -> RenderOutputReceipt:
    """Take the renderer's finished file into the store; publish verifies it later."""
    try:
        with safe_render_errors(
            unavailable=(status.HTTP_404_NOT_FOUND, "render_output_unavailable")
        ):
            received = await service.receive_output(render_job_id, request.stream())
    except RenderOutputTooLarge:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={"code": "render_output_too_large"},
        ) from None
    return RenderOutputReceipt(size_bytes=received.size_bytes, checksum=received.checksum)


@router.post("/{render_job_id}/events", include_in_schema=False)
async def ingest_render_event(
    render_job_id: OpaqueId, event: RenderJobEvent, service: ServiceDependency
) -> RenderEventAck:
    """Persist one sequenced renderer report before it affects public state."""
    if event.render_job_id != render_job_id:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_render_event"},
        )
    with safe_render_errors(unavailable=(status.HTTP_409_CONFLICT, "render_output_invalid")):
        job = await service.ingest_event(render_job_id, event)
    return RenderEventAck(status=job.status, last_event_sequence=job.last_event_sequence)
