"""A workspace's own asset library: SFX, clips, backsound and images (spec 2026-11-13)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from thoth_control_plane.domain.models import StrictModel

LibraryKind = Literal["sfx", "clip", "backsound", "image"]

#: Display names are cut here; the stored object's name never comes from them.
NAME_MAX = 120


class WorkspaceAsset(StrictModel):
    """The public view of one library item; its storage locator stays on the server."""

    asset_id: Annotated[str, Field(pattern=r"^lib_[A-Za-z0-9_]{1,64}$")]
    workspace_id: Annotated[str, Field(min_length=1, max_length=128)]
    kind: LibraryKind
    name: Annotated[str, Field(min_length=1, max_length=NAME_MAX)]
    labels: dict[str, object] = Field(default_factory=dict)
    media_type: Annotated[str, Field(min_length=1, max_length=100)]
    checksum: Annotated[str, Field(min_length=1, max_length=100)]
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    has_audio: bool = False
    created_at: datetime


class WorkspaceAssetRecord(StrictModel):
    """A library item with where its media is stored; never returned by a route."""

    asset: WorkspaceAsset
    location: Annotated[str, Field(min_length=1, max_length=500)]
