"""A project's Studio documents, newest revision first (spec 2026-10-18, section 3.6)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import Field

from thoth_control_plane.domain.models import OpaqueId, StrictModel

DocumentState: TypeAlias = Literal["draft", "in_review", "approved", "rendering", "rendered"]
RENDERING = frozenset({"preparing", "rendering", "finalizing"})


class EditDocumentListItem(StrictModel):
    document_id: OpaqueId
    revision: Annotated[int, Field(gt=0)]
    updated_at: datetime
    label: Annotated[str, Field(min_length=1, max_length=120)]
    imported: bool
    # Restyle B9 (DESIGN §13.5): where the draft stands, and the run it was opened from.
    state: DocumentState = "draft"
    render_percent: Annotated[int, Field(ge=0, le=100)] | None = None
    source_workflow_id: OpaqueId | None = None
    # Filled by the API from the source run's row, never stored with the draft.
    source_platform: str | None = None
    source_title: str | None = None
    source_owner_handle: str | None = None
    source_has_post_card: bool = False


def document_state(
    revision: int,
    *,
    render: tuple[str, int] | None,
    decision: str | None,
    reviewed: bool,
) -> DocumentState:
    """A render in progress, then the latest revision's video, approval and review, else draft.

    ``render`` is the newest render job's status and revision; ``decision`` and ``reviewed``
    describe the review of the latest revision only.
    """
    if render is not None and render[0] in RENDERING:
        return "rendering"
    if render == ("completed", revision):
        return "rendered"
    if decision == "approved":
        return "approved"
    return "in_review" if reviewed else "draft"


class EditDocumentListPage(StrictModel):
    items: list[EditDocumentListItem]
    next_cursor: str | None


def document_label(document_json: dict[str, Any]) -> str:
    """The first non-empty text clip heading, else `Untitled draft`."""
    for clip in document_json.get("clips", []):
        heading = clip.get("heading") if clip.get("kind") == "text" else None
        if isinstance(heading, str) and heading.strip():
            return heading.strip()[:120]
    return "Untitled draft"
