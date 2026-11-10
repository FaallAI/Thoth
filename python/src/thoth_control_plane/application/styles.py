"""Applying a style to a draft (spec 2026-11-10, 6): one revision, then a new narration.

The look and cuts go in as one patch of typed operations, so one undo restores the draft. The
narration that follows writes a script in the style and waits for approval before any voice is
paid for; a refusal to start it leaves the look applied and says why.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Protocol

from pydantic import Field

from thoth_control_plane.application.edit_documents import (
    EditDocumentRefused,
    EditDocumentService,
    RestoreRevisionRequest,
)
from thoth_control_plane.application.narrations import (
    NarrationNotFound,
    NarrationRefused,
    NarrationService,
    NarrationUnavailable,
)
from thoth_control_plane.domain import EditDocument
from thoth_control_plane.domain.edit_document_operations import EditDocumentPatch
from thoth_control_plane.domain.edit_document_v2 import EditDocumentV2
from thoth_control_plane.domain.models import OpaqueId, StrictModel
from thoth_control_plane.domain.narration import NarrationState
from thoth_control_plane.domain.style_apply import style_operations
from thoth_control_plane.domain.style_templates import StyleTemplate

logger = logging.getLogger(__name__)

#: A style's narration may be stopped by its undo until the voice is being made (paid for).
UNDOABLE = frozenset({"transcribing", "scripting", "awaiting_approval"})


class StyleTemplates(Protocol):
    async def list_for(self, workspace_id: str) -> list[StyleTemplate]: ...
    async def get(self, template_id: str, workspace_id: str) -> StyleTemplate | None: ...


class StyleNotFound(LookupError):
    """No such style template for this workspace."""


class StyleRefused(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class StyleSummary(StrictModel):
    template_id: OpaqueId
    name: Annotated[str, Field(min_length=1, max_length=120)]
    revision: Annotated[int, Field(gt=0)]


class ApplyStyleRequest(StrictModel):
    template_id: OpaqueId
    base_revision: Annotated[int, Field(gt=0)]


class AppliedStyleResult(StrictModel):
    document: EditDocument
    previous_revision: Annotated[int, Field(gt=0)]
    narration: NarrationState | None = None
    #: Why the narration did not start; the look is applied all the same.
    narration_refused: str | None = None


class StyleService:
    def __init__(
        self,
        templates: StyleTemplates,
        documents: EditDocumentService,
        narrations: NarrationService | None,
        roles: Callable[[str, str], Awaitable[dict[str, str]]],
    ) -> None:
        self._templates = templates
        self._documents = documents
        self._narrations = narrations
        self._roles = roles

    async def list(self, workspace_id: str) -> list[StyleSummary]:
        return [
            StyleSummary(template_id=t.template_id, name=t.name, revision=t.revision)
            for t in await self._templates.list_for(workspace_id)
        ]

    async def _narration(self, project_id: str, document_id: str) -> NarrationState | None:
        if self._narrations is None:
            return None
        try:
            return await self._narrations.get(project_id, document_id)
        except (NarrationNotFound, NarrationUnavailable):
            return None

    async def apply(
        self, workspace_id: str, project_id: str, document_id: str, request: ApplyStyleRequest
    ) -> AppliedStyleResult:
        if self._narrations is not None and await self._narrations.is_locked(
            project_id, document_id
        ):
            raise StyleRefused("narration_in_progress")
        template = await self._templates.get(request.template_id, workspace_id)
        if template is None:
            raise StyleNotFound()
        document = await self._documents.get_latest(project_id, document_id)
        if not isinstance(document, EditDocumentV2):
            raise EditDocumentRefused()
        operations = style_operations(
            document, template, await self._roles(project_id, document_id)
        )
        updated = await self._documents.apply_patch(
            project_id,
            document_id,
            EditDocumentPatch(base_revision=request.base_revision, operations=operations),
        )
        logger.info(
            "style applied document=%s style=%s operations=%d",
            document_id,
            template.template_id,
            len(operations),
        )
        narration, refused = None, None
        if self._narrations is None:
            refused = "narration_unavailable"
        else:
            previous = await self._narration(project_id, document_id)
            try:
                narration = await self._narrations.start(
                    project_id,
                    document_id,
                    restart=previous is not None and previous.status == "completed",
                )
            except NarrationRefused as error:
                refused = error.code
            except NarrationUnavailable:
                refused = "narration_unavailable"
        if refused:
            logger.warning("style narration not started document=%s code=%s", document_id, refused)
        return AppliedStyleResult(
            document=updated,
            previous_revision=document.revision,
            narration=narration,
            narration_refused=refused,
        )

    async def undo(
        self, project_id: str, document_id: str, request: RestoreRevisionRequest
    ) -> EditDocument:
        """Undo a style: stop its narration if no voice is being made yet, then restore."""
        state = await self._narration(project_id, document_id)
        if state is not None and self._narrations is not None:
            if state.status in UNDOABLE:
                await self._narrations.cancel(project_id, document_id)
            elif state.status in {"voicing", "writing"}:
                raise StyleRefused("narration_in_progress")
        return await self._documents.restore_revision(project_id, document_id, request)
