"""Stored workflow runs, listed per project (spec 2026-10-18, section 3.3)."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field

from thoth_control_plane.domain.models import (
    Actor,
    OpaqueId,
    ProjectId,
    StageSummary,
    StrictModel,
    WorkflowSource,
    WorkflowStep,
    WorkflowSummary,
)
from thoth_control_plane.domain.source_accounts import SourcePlatform

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
    # Restyle B2: what a list row shows. Absent until the source report is read.
    title: str | None = None
    owner_handle: str | None = None
    has_post_card: bool = Field(default_factory=lambda: False)
    stages: list[StageSummary] = Field(default_factory=list)
    current_step: WorkflowStep | None = None


class WorkflowRunPage(StrictModel):
    items: list[WorkflowRun]
    next_cursor: str | None


class MoveWorkflow(StrictModel):
    project_id: ProjectId


class InboxRun(StrictModel):
    """One run awaiting the caller: an approval or an unacknowledged failure (spec G5)."""

    workflow_id: OpaqueId
    project_id: ProjectId | None
    display_url: str
    platform: str
    status: WorkflowRunStatus
    updated_at: datetime
    failure_code: str | None = None
    title: str | None = None


class InboxAccount(StrictModel):
    """A source account in cooldown or trouble, for platform admins only (spec G5).

    Deliberately carries no cookie, cookie name or proxy data."""

    account_id: str
    platform: SourcePlatform
    label: str
    status: str
    cooldown_until: datetime | None = None


class Inbox(StrictModel):
    approvals: list[InboxRun] = Field(default_factory=list)
    failures: list[InboxRun] = Field(default_factory=list)
    accounts: list[InboxAccount] = Field(default_factory=list)


@dataclass(frozen=True)
class StoredRun:
    workflow_id: str
    project_id: str | None
    actor_type: str
    actor_id: str
    display_url: str
    platform: str
    status: str
    history_expired: bool
    summary: WorkflowSummary | None
    created_at: datetime
    updated_at: datetime
    # Editor migration 0020: set once by an explicit acknowledge (inbox spec G5).
    acknowledged_at: datetime | None = None
    # Editor migration 0023: read once from the source report (restyle B2).
    title: str | None = None
    owner_handle: str | None = None
    post_card_location: str | None = None

    def owned_by(self, actor: Actor) -> bool:
        return (self.actor_type, self.actor_id) == (actor.actor_type, actor.actor_id)

    def to_run(self, current_step: WorkflowStep | None = None) -> WorkflowRun:
        return WorkflowRun(
            workflow_id=self.workflow_id,
            project_id=self.project_id,
            source={"display_url": self.display_url, "platform": self.platform},
            status=self.status,
            history_expired=self.history_expired,
            artifact_count=len(self.summary.artifacts) if self.summary else 0,
            created_at=self.created_at,
            updated_at=self.updated_at,
            title=self.title,
            owner_handle=self.owner_handle,
            has_post_card=self.post_card_location is not None,
            stages=self.summary.stages if self.summary else [],
            current_step=current_step,
        )

    def with_(self, **changes: Any) -> StoredRun:
        return replace(self, **changes)


#: A list row's title: the first line of the post, at most this many characters.
TITLE_LENGTH = 140


def listing_details(content: str) -> tuple[str, str | None, str | None]:
    """(title, owner handle, post card location) from a source report, any schema version.

    Read leniently: a report that does not parse still settles to an empty title, so the
    listing never reads it again and never fails on it."""
    try:
        report = json.loads(content)
        post = report.get("post") or {}
        text = post.get("text") or post.get("caption") or ""
        owner = post.get("owner_handle")
        card = (report.get("post_card") or {}).get("location")
    except (ValueError, AttributeError):
        return "", None, None
    lines = (" ".join(line.split()) for line in str(text).splitlines())
    first = next((line for line in lines if line), "")
    if len(first) > TITLE_LENGTH:
        first = first[: TITLE_LENGTH - 1] + "…"
    return (
        first,
        owner if isinstance(owner, str) and owner else None,
        card if isinstance(card, str) and card else None,
    )
