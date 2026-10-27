"""Story Assist: one text proposal for one beat, never stored (spec 2026-10-27, section 7)."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import Field

from thoth_control_plane.domain.edit_document_operations import EditDocumentOperation
from thoth_control_plane.domain.models import OpaqueId, ProjectId, StrictModel

BeatId: TypeAlias = Literal["hook", "main", "evidence", "reactions", "footage", "outro"]
#: The reading speed the importer lays cards out at (domain/studio_layout.READING_CPS).
ASSIST_READING_CPS = 15
#: Safe failure codes the activity reports; never a provider message.
AssistFailure: TypeAlias = Literal[
    "provider_timeout", "provider_rate_limited", "provider_unavailable", "invalid_provider_output"
]


class StoryAssistRequest(StrictModel):
    base_revision: Annotated[int, Field(gt=0)]
    beat: BeatId
    clip_ids: Annotated[list[OpaqueId], Field(min_length=1, max_length=20)]


class StoryAssistProposal(StrictModel):
    proposal_id: str
    title: str
    reason: str
    operations: list[EditDocumentOperation]


class StoryAssistInput(StrictModel):
    """What crosses the activity boundary: the prompt text and the model, no credential."""

    project_id: ProjectId
    provider_id: str
    model_id: str
    system: Annotated[str, Field(min_length=1, max_length=12_000)]
    user: Annotated[str, Field(min_length=1, max_length=12_000)]


class StoryAssistOutput(StrictModel):
    code: AssistFailure | None = None
    title: str = ""
    reason: str = ""
    text: str = ""
