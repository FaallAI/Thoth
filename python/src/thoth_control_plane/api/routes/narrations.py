"""Narration routes (spec 2026-10-31): a draft's narration, its decision, beats, preset, SFX."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import Field

from thoth_control_plane.api.dependencies import current_actor
from thoth_control_plane.application.edit_documents import EditDocumentNotFound
from thoth_control_plane.application.narrations import (
    NarrationNotFound,
    NarrationRefused,
    NarrationService,
    NarrationUnavailable,
)
from thoth_control_plane.domain import Actor
from thoth_control_plane.domain.editor_assets import EditorAsset
from thoth_control_plane.domain.models import StrictModel
from thoth_control_plane.domain.narration import (
    BeatId,
    NarrationDecision,
    NarrationPreset,
    NarrationScript,
    NarrationState,
    NarrationStoreUnavailable,
    StoredPreset,
)

router = APIRouter(tags=["narration"])
DOCUMENT = "/projects/{project_id}/edit-documents/{document_id}/narration"


class BeatText(StrictModel):
    text: Annotated[str, Field(min_length=1, max_length=2000)]


class SavePreset(StrictModel):
    base_revision: Annotated[int, Field(ge=0)]
    preset: NarrationPreset


class SfxSummary(StrictModel):
    """A library entry as Studio sees it: never its storage location."""

    sfx_id: str
    file_name: str
    duration_seconds: float
    labels: dict[str, Any]


def get_narration_service(request: Request) -> NarrationService:
    return request.app.state.narration_service


Service = Annotated[NarrationService, Depends(get_narration_service)]
Caller = Annotated[Actor, Depends(current_actor)]


async def _answer(work):  # type: ignore[no-untyped-def]
    try:
        return await work
    except (NarrationNotFound, EditDocumentNotFound) as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    except NarrationRefused as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail={"code": error.code}
        ) from error
    except (NarrationUnavailable, NarrationStoreUnavailable) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "narration_unavailable"},
        ) from error


@router.post(DOCUMENT, response_model=NarrationState, status_code=status.HTTP_202_ACCEPTED)
async def start_narration(
    project_id: str, document_id: str, _: Caller, service: Service
) -> NarrationState:
    """Create narration: nothing is spent until the operator approves the script."""
    return await _answer(service.start(project_id, document_id))


@router.post(
    f"{DOCUMENT}/restart", response_model=NarrationState, status_code=status.HTTP_202_ACCEPTED
)
async def restart_narration(
    project_id: str, document_id: str, _: Caller, service: Service
) -> NarrationState:
    """Write a finished narration again from the draft as it is now (a new script, approved
    again before any voice); new beats such as an added Hook are included."""
    return await _answer(service.start(project_id, document_id, restart=True))


@router.get(DOCUMENT, response_model=NarrationState)
async def read_narration(
    project_id: str, document_id: str, _: Caller, service: Service
) -> NarrationState:
    return await _answer(service.get(project_id, document_id))


@router.post(
    f"{DOCUMENT}/decision", response_model=NarrationState, status_code=status.HTTP_202_ACCEPTED
)
async def decide_narration(
    project_id: str, document_id: str, decision: NarrationDecision, _: Caller, service: Service
) -> NarrationState:
    return await _answer(service.decide(project_id, document_id, decision))


@router.post(
    f"{DOCUMENT}/cancel", response_model=NarrationState, status_code=status.HTTP_202_ACCEPTED
)
async def cancel_narration(
    project_id: str, document_id: str, _: Caller, service: Service
) -> NarrationState:
    """Stop a running narration; nothing further is spent and the draft unlocks."""
    return await _answer(service.cancel(project_id, document_id))


@router.put(f"{DOCUMENT}/beats/{{beat}}", response_model=NarrationScript)
async def edit_narration_beat(
    project_id: str, document_id: str, beat: BeatId, body: BeatText, _: Caller, service: Service
) -> NarrationScript:
    return await _answer(service.set_beat_text(project_id, document_id, beat, body.text))


@router.post(
    f"{DOCUMENT}/beats/{{beat}}/revoice",
    response_model=NarrationState,
    status_code=status.HTTP_202_ACCEPTED,
)
async def revoice_narration_beat(
    project_id: str, document_id: str, beat: BeatId, _: Caller, service: Service
) -> NarrationState:
    return await _answer(service.revoice(project_id, document_id, beat))


@router.get("/projects/{project_id}/narration-preset", response_model=StoredPreset)
async def read_narration_preset(project_id: str, _: Caller, service: Service) -> StoredPreset:
    return await _answer(service.get_preset(project_id))


@router.put("/projects/{project_id}/narration-preset", response_model=StoredPreset)
async def save_narration_preset(
    project_id: str, body: SavePreset, _: Caller, service: Service
) -> StoredPreset:
    return await _answer(service.save_preset(project_id, body.preset, body.base_revision))


@router.post("/projects/{project_id}/sfx/{sfx_id}/asset", response_model=EditorAsset)
async def add_sfx_to_project(
    project_id: str, sfx_id: str, _: Caller, service: Service
) -> EditorAsset:
    """A library sound effect as one of the project's assets, for the Timeline to place."""
    return await _answer(service.add_sfx(project_id, sfx_id))


@router.get("/sfx", response_model=list[SfxSummary])
async def list_sfx(_: Caller, service: Service) -> list[SfxSummary]:
    entries = await _answer(service.list_sfx())
    return [
        SfxSummary(
            sfx_id=entry.sfx_id,
            file_name=entry.file_name,
            duration_seconds=entry.duration_seconds,
            labels=entry.labels,
        )
        for entry in entries
    ]
