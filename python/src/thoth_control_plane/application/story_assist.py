"""Story Assist: one text proposal for a beat, applied only through the editor's patch.

Spec 2026-10-27, section 7. The model runs in the worker (the provider credentials live
there); this service builds the prompt, checks the answer against the clip's reading time,
and turns it into one revision-bound operation. Nothing is stored.
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable
from typing import Any, Protocol
from uuid import uuid4

from thoth_control_plane.application.ports import EditDocumentRevisionConflict
from thoth_control_plane.domain.edit_document_operations import ReplaceText
from thoth_control_plane.domain.edit_document_v2 import TimelineCaptionClip, TimelineTextClip
from thoth_control_plane.domain.prompts import PROMPT_STARTERS
from thoth_control_plane.domain.story_assist import (
    ASSIST_READING_CPS,
    StoryAssistInput,
    StoryAssistOutput,
    StoryAssistProposal,
    StoryAssistRequest,
)
from thoth_control_plane.domain.timeline_operations import SetCaptionCueText

STAGE = "story_assist"
DESCRIPTION_LIMIT = 500
#: The longest heading or caption cue a document holds (edit_documents.ShortText).
TEXT_LIMIT = 300
#: Always asked for, whatever a project's saved prompt says, so the answer stays parseable.
ANSWER_CONTRACT = (
    'Answer with one JSON object: {"title": a few words naming the change, '
    '"reason": one sentence on why it reads better, "text": the new text}.'
)


class StoryAssistUnavailable(RuntimeError):
    """No workflow runtime, or the provider timed out, refused or failed."""


class StoryAssistNotConfigured(LookupError):
    """The project chose no provider and model for the story_assist stage."""


class StoryAssistInvalidOutput(ValueError):
    """The answer was not the JSON asked for, or does not fit the clip."""


class StoryAssistNoText(ValueError):
    """None of the chosen clips holds text Assist can rewrite."""


class StoryAssistGateway(Protocol):
    async def complete(self, request: StoryAssistInput) -> StoryAssistOutput: ...


StoryContext = Callable[[str, str], Awaitable[tuple[str, str] | None]]


class StoryAssistService:
    def __init__(
        self,
        *,
        documents: Any,
        preferences: Any,
        prompts: Any | None,
        context: StoryContext | None,
        gateway: StoryAssistGateway | None,
    ) -> None:
        self._documents = documents
        self._preferences = preferences
        self._prompts = prompts
        self._context = context
        self._gateway = gateway

    async def propose(
        self, project_id: str, document_id: str, request: StoryAssistRequest
    ) -> StoryAssistProposal:
        document = await self._documents.get_latest(project_id, document_id)
        if document.revision != request.base_revision:
            raise EditDocumentRevisionConflict(document)
        target = next(
            (
                clip
                for clip_id in request.clip_ids
                for clip in document.clips
                if clip.clip_id == clip_id
                and isinstance(clip, TimelineTextClip | TimelineCaptionClip)
            ),
            None,
        )
        if target is None:
            raise StoryAssistNoText()
        seconds = target.duration_in_frames / document.canvas.fps
        limit = min(TEXT_LIMIT, int(seconds * ASSIST_READING_CPS))
        if limit < 1:
            raise StoryAssistNoText()  # shown too briefly to read: no call is worth making
        preference = await self._preferences.get_preference(project_id, STAGE)
        if preference is None or not self._can_rewrite(preference):
            raise StoryAssistNotConfigured()
        if self._gateway is None:
            raise StoryAssistUnavailable()

        current = target.heading if isinstance(target, TimelineTextClip) else target.cues[0].text
        title, description = (
            await self._context(project_id, document_id) if self._context else None
        ) or ("", "")
        user = "\n".join(
            line
            for line in (
                f"Beat: {request.beat}",
                f"Current text: {current}",
                f"Video title: {title}" if title else "",
                f"Post description: {description[:DESCRIPTION_LIMIT]}" if description else "",
                f"The text shows for {seconds:.1f} seconds; at {ASSIST_READING_CPS} characters "
                f"per second it may be at most {limit} characters.",
            )
            if line
        )
        output = await self._gateway.complete(
            StoryAssistInput(
                project_id=project_id,
                provider_id=preference.provider_id,
                model_id=preference.model_id,
                system=await self._system(project_id),
                user=user,
            )
        )
        if output.code == "invalid_provider_output":
            raise StoryAssistInvalidOutput()
        if output.code is not None:
            raise StoryAssistUnavailable()
        text = output.text.strip()
        if not text or len(text) > limit:
            raise StoryAssistInvalidOutput()

        operation_id = f"op_assist_{uuid4().hex}"
        operation = (
            ReplaceText(
                kind="replace_text",
                operation_id=operation_id,
                clip_id=target.clip_id,
                field="heading",
                value=text,
            )
            if isinstance(target, TimelineTextClip)
            else SetCaptionCueText(
                kind="set_caption_cue_text",
                operation_id=operation_id,
                clip_id=target.clip_id,
                cue_index=0,
                text=text,
            )
        )
        return StoryAssistProposal(
            proposal_id=f"assist_{uuid4().hex}",
            title=output.title.strip()[:120],
            reason=output.reason.strip()[:300],
            operations=[operation],
        )

    def _can_rewrite(self, preference: Any) -> bool:
        """The chosen model offers `improve`, the capability Assist's rewrites need."""
        providers = getattr(self._preferences, "list_providers", None)
        if providers is None:
            return True
        return any(
            provider.provider_id == preference.provider_id
            and any(
                model.model_id == preference.model_id and "improve" in model.capabilities
                for model in provider.models
            )
            for provider in providers()
        )

    async def _system(self, project_id: str) -> str:
        """The project's saved prompt for the stage, else the starter; the contract always."""
        prompt = PROMPT_STARTERS[STAGE].body
        if self._prompts is not None:
            # No binding saved, or the prompt store is down: the starter stands.
            with contextlib.suppress(Exception):
                prompt = (await self._prompts.get_resolved_prompt(project_id, STAGE)).visible_text
        return f"{prompt}\n\n{ANSWER_CONTRACT}"
