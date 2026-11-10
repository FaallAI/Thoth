"""Prompt Lab application use cases with safe typed errors."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any
from uuid import uuid4

from thoth_control_plane.application.ports import (
    PromptBindingNotFound,
    PromptBindingRevisionConflict,
    PromptLabRepository,
    PromptTemplateNotFound,
    PromptTemplateRevisionConflict,
)
from thoth_control_plane.domain.models import ProjectId
from thoth_control_plane.domain.prompts import (
    PROMPT_STAGES,
    STYLE_STAGE,
    ProjectPromptBinding,
    PromptStageDefinition,
    PromptStageId,
    PromptTemplateRevision,
    ResolvedPromptDraft,
    SaveProjectPromptBindingRequest,
    SavePromptTemplateRequest,
    resolve_prompt_draft,
)
from thoth_control_plane.domain.style_templates import BUILT_IN_STYLES, StyleTemplate

logger = logging.getLogger(__name__)


class PromptLabStoreUnavailable(Exception):
    """The optional prompt lab persistence is not configured or reachable."""


class PromptStageNotRegistered(Exception):
    """The requested authoring stage is not part of the draft registry."""


class PromptStageMismatch(Exception):
    """The referenced template does not belong to the binding stage."""


_PASSTHROUGH_ERRORS = (
    PromptTemplateRevisionConflict,
    PromptBindingRevisionConflict,
    PromptTemplateNotFound,
    PromptBindingNotFound,
)


class PromptLabService:
    """Application service for authoring project-scoped prompt templates."""

    def __init__(self, repository: PromptLabRepository | None) -> None:
        self._repository = repository

    def list_stages(
        self, styles: Sequence[StyleTemplate] = ()
    ) -> tuple[PromptStageDefinition, ...]:
        """The backend-owned stage registry, then one `style_script` entry per style template."""
        return (
            *PROMPT_STAGES,
            *(
                PromptStageDefinition(
                    stage_id=STYLE_STAGE,
                    label=f"{style.name} script",
                    status="draft_only",
                    variant=style.template_id,
                )
                for style in styles
            ),
        )

    def _require_stage(self, stage_id: str) -> None:
        known = {stage.stage_id for stage in PROMPT_STAGES} | {STYLE_STAGE}
        if stage_id not in known:
            raise PromptStageNotRegistered()

    def _require_variant(self, stage_id: str, variant: str) -> None:
        """A variant names a style, and only a style's stage has one; the built-in styles are
        the only ones until the style editor (deferred minor, 2026-11-10)."""
        self._require_stage(stage_id)
        if (stage_id == STYLE_STAGE) != (variant in BUILT_IN_STYLES):
            raise PromptStageNotRegistered()

    def _require_repository(self) -> PromptLabRepository:
        if self._repository is None:
            raise PromptLabStoreUnavailable()
        return self._repository

    async def list_templates(
        self, project_id: ProjectId, stage_id: PromptStageId
    ) -> list[PromptTemplateRevision]:
        self._require_stage(stage_id)
        try:
            return await self._require_repository().list_template_heads(
                project_id=project_id, stage_id=stage_id
            )
        except _PASSTHROUGH_ERRORS:
            raise
        except Exception as error:
            raise PromptLabStoreUnavailable() from error

    async def save_template(
        self, project_id: ProjectId, request: SavePromptTemplateRequest
    ) -> PromptTemplateRevision:
        template_id = request.template_id or f"ptpl_{uuid4().hex}"
        try:
            return await self._require_repository().save_template(
                project_id=project_id,
                template_id=template_id,
                base_revision=request.base_revision,
                stage_id=request.stage_id,
                language=request.language,
                body=request.body,
            )
        except _PASSTHROUGH_ERRORS:
            raise
        except Exception as error:
            raise PromptLabStoreUnavailable() from error

    async def get_binding(
        self, project_id: ProjectId, stage_id: PromptStageId, *, variant: str = ""
    ) -> ProjectPromptBinding | None:
        self._require_variant(stage_id, variant)
        try:
            return await self._require_repository().get_binding(
                project_id=project_id, stage_id=stage_id, variant=variant
            )
        except _PASSTHROUGH_ERRORS:
            raise
        except Exception as error:
            raise PromptLabStoreUnavailable() from error

    async def save_binding(
        self,
        project_id: ProjectId,
        stage_id: PromptStageId,
        request: SaveProjectPromptBindingRequest,
        *,
        variant: str = "",
    ) -> ProjectPromptBinding:
        self._require_variant(stage_id, variant)
        template = await self.get_template_revision(
            project_id, request.template_id, request.template_revision
        )
        if template.stage_id != stage_id:
            raise PromptStageMismatch()
        try:
            return await self._require_repository().save_binding(
                project_id=project_id, stage_id=stage_id, request=request, variant=variant
            )
        except _PASSTHROUGH_ERRORS:
            raise
        except Exception as error:
            raise PromptLabStoreUnavailable() from error

    async def get_template_revision(
        self, project_id: ProjectId, template_id: str, revision: int
    ) -> PromptTemplateRevision:
        try:
            template = await self._require_repository().get_template_revision(
                project_id=project_id, template_id=template_id, revision=revision
            )
        except _PASSTHROUGH_ERRORS:
            raise
        except Exception as error:
            raise PromptLabStoreUnavailable() from error
        if template is None:
            raise PromptTemplateNotFound()
        return template

    async def get_resolved_prompt(
        self, project_id: ProjectId, stage_id: PromptStageId, *, variant: str = ""
    ) -> ResolvedPromptDraft:
        self._require_variant(stage_id, variant)
        binding = await self.get_binding(project_id, stage_id, variant=variant)
        if binding is None:
            raise PromptBindingNotFound()
        template = await self.get_template_revision(
            project_id, binding.template_id, binding.template_revision
        )
        try:
            return resolve_prompt_draft(template, binding)
        except ValueError as error:
            raise PromptStageMismatch() from error


async def resolve_style_prompt(prompts: Any, project_id: str, template: StyleTemplate) -> str:
    """A style's script prompt: the project's binding for that style, else the style's starter."""
    if prompts is not None:
        try:
            resolved = await prompts.get_resolved_prompt(
                project_id, STYLE_STAGE, variant=template.template_id
            )
            return resolved.visible_text
        except PromptBindingNotFound:
            pass  # no binding saved: the starter, as designed
        except Exception as error:  # the prompt store is down: the starter, said out loud
            logger.warning(
                "style prompt fell back to the starter template=%s error=%s",
                template.template_id,
                type(error).__name__,
            )
    return template.narration.starter
