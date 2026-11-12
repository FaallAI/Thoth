"""The caller's workspace asset library (spec 2026-11-13).

The workspace is always the caller's own; another workspace's item answers exactly like a
missing one. No route returns a storage locator.
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request, Response, status

from thoth_control_plane.api.dependencies import current_actor
from thoth_control_plane.api.ranged import ranged_response
from thoth_control_plane.api.routes.editor_assets import PREVIEW_HEADERS
from thoth_control_plane.application.editor_asset_ports import (
    EditorAssetMediaInvalid,
    EditorAssetUploadTooLarge,
)
from thoth_control_plane.application.editor_asset_uploads import UPLOAD_MAX_BYTES, UPLOAD_TYPES
from thoth_control_plane.application.workspace_library import (
    LibraryItemNotFound,
    LibraryKindRefused,
    LibraryUnavailable,
    WorkspaceLibraryService,
)
from thoth_control_plane.auth.models import actor_workspace_id
from thoth_control_plane.domain import Actor
from thoth_control_plane.domain.editor_assets import EditorAsset
from thoth_control_plane.domain.models import PROJECT_ID_PATTERN, StrictModel
from thoth_control_plane.domain.workspace_assets import LibraryKind, WorkspaceAsset

router = APIRouter()

AssetId = Annotated[str, Path(pattern=r"^lib_[A-Za-z0-9_]{1,64}$")]


class LibraryPatch(StrictModel):
    """Only what the page edits; a missing field stays as it is."""

    name: str | None = None
    labels: dict[str, object] | None = None
    kind: LibraryKind | None = None


def _service(request: Request) -> WorkspaceLibraryService:
    service = getattr(request.app.state, "workspace_library_service", None)
    if service is None:
        raise _refused(status.HTTP_503_SERVICE_UNAVAILABLE, "library_unavailable")
    return service


Service = Annotated[WorkspaceLibraryService, Depends(_service)]
Caller = Annotated[Actor, Depends(current_actor)]


def _refused(status_code: int, code: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code})


def _workspace(actor: Actor) -> str:
    return actor_workspace_id(actor.actor_id)


async def _answer(work):  # type: ignore[no-untyped-def]
    try:
        return await work
    except LibraryItemNotFound as error:
        raise _refused(status.HTTP_404_NOT_FOUND, "library_item_not_found") from error
    except LibraryKindRefused as error:
        raise _refused(status.HTTP_422_UNPROCESSABLE_CONTENT, "kind_mismatch") from error
    except LibraryUnavailable as error:
        raise _refused(status.HTTP_503_SERVICE_UNAVAILABLE, "library_unavailable") from error


@router.get("/library", response_model=list[WorkspaceAsset])
async def list_library(actor: Caller, service: Service) -> list[WorkspaceAsset]:
    return await _answer(service.list(_workspace(actor)))


@router.post(
    "/library",
    response_model=WorkspaceAsset,
    status_code=status.HTTP_201_CREATED,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                media_type: {"schema": {"type": "string", "format": "binary"}}
                for media_type in UPLOAD_TYPES
            },
        }
    },
)
async def upload_library_item(
    request: Request,
    actor: Caller,
    service: Service,
    # No length limit: an encoded emoji name runs long, and `display_name` trims it anyway.
    file_name: Annotated[str, Header(alias="X-File-Name")] = "untitled",
) -> WorkspaceAsset:
    """Accept one streamed media body; its URL-encoded name only labels it."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > UPLOAD_MAX_BYTES:
        raise _refused(status.HTTP_413_CONTENT_TOO_LARGE, "upload_too_large")
    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    try:
        return await _answer(
            service.upload(_workspace(actor), media_type, request.stream(), unquote(file_name))
        )
    except EditorAssetUploadTooLarge as error:
        raise _refused(status.HTTP_413_CONTENT_TOO_LARGE, "upload_too_large") from error
    except EditorAssetMediaInvalid as error:
        if error.code == "unsupported_media_type":
            raise _refused(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, error.code) from error
        raise _refused(status.HTTP_422_UNPROCESSABLE_CONTENT, error.code) from error


@router.patch("/library/{asset_id}", response_model=WorkspaceAsset)
async def update_library_item(
    asset_id: AssetId, body: LibraryPatch, actor: Caller, service: Service
) -> WorkspaceAsset:
    return await _answer(
        service.update(
            _workspace(actor), asset_id, name=body.name, labels=body.labels, kind=body.kind
        )
    )


@router.delete("/library/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_library_item(asset_id: AssetId, actor: Caller, service: Service) -> Response:
    if not await _answer(service.delete(_workspace(actor), asset_id)):
        raise _refused(status.HTTP_404_NOT_FOUND, "library_item_not_found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/library/{asset_id}/media",
    response_class=Response,
    responses={status.HTTP_200_OK: {"content": {"application/octet-stream": {}}}},
)
async def stream_library_item(
    asset_id: AssetId, request: Request, actor: Caller, service: Service
) -> Response:
    record, size = await _answer(service.stored(_workspace(actor), asset_id))
    return ranged_response(
        size=size,
        read=lambda start, end: service.read(record.location, start, end),
        media_type=record.asset.media_type,
        range_header=request.headers.get("range"),
        headers=PREVIEW_HEADERS,
    )


@router.post(
    "/projects/{project_id}/library/{asset_id}/asset",
    response_model=EditorAsset,
    status_code=status.HTTP_201_CREATED,
)
async def add_library_item_to_project(
    project_id: Annotated[str, Path(pattern=PROJECT_ID_PATTERN)],
    asset_id: AssetId,
    actor: Caller,
    service: Service,
) -> EditorAsset:
    """The draft's own copy of one library item; `current_actor` guards the project."""
    return await _answer(service.add_to_project(_workspace(actor), project_id, asset_id))
