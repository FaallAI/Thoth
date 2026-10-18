"""A project's Studio documents, newest revision first (spec 2026-10-18, section 3.6)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from pydantic import Field

from thoth_control_plane.domain.models import OpaqueId, StrictModel


class EditDocumentListItem(StrictModel):
    document_id: OpaqueId
    revision: Annotated[int, Field(gt=0)]
    updated_at: datetime
    label: Annotated[str, Field(min_length=1, max_length=120)]
    imported: bool


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
