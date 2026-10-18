"""Stored workflow runs, listed per project (spec 2026-10-18, section 3.3)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from thoth_control_plane.domain.models import OpaqueId, ProjectId, StrictModel, WorkflowSource

WorkflowRunStatus = Literal[
    "queued", "running", "awaiting_approval", "succeeded", "failed", "cancelled", "unknown"
]
#: Rows a listing still asks Temporal about.
UNSETTLED = frozenset({"queued", "running", "awaiting_approval", "unknown"})


class WorkflowRun(StrictModel):
    workflow_id: OpaqueId
    project_id: ProjectId | None
    source: WorkflowSource
    status: WorkflowRunStatus
    history_expired: bool
    artifact_count: Annotated[int, Field(ge=0)]
    created_at: datetime
    updated_at: datetime


class WorkflowRunPage(StrictModel):
    items: list[WorkflowRun]
    next_cursor: str | None


class MoveWorkflow(StrictModel):
    project_id: ProjectId
