"""Story Assist's provider call, inside the worker that holds the credentials (spec 7)."""

from __future__ import annotations

import asyncio

from temporalio import activity

from thoth_control_plane import metering
from thoth_control_plane.activities.prompt_proposal import _safe_failure_code
from thoth_control_plane.domain.story_assist import StoryAssistInput, StoryAssistOutput


class StoryAssistActivity:
    """One provider call; the answer's three strings, or a safe failure code."""

    def __init__(self, *, provider: object) -> None:
        self._provider = provider

    @activity.defn(name="run_story_assist")
    async def run(self, request: StoryAssistInput) -> StoryAssistOutput:
        # The call is the project's workspace's model use.
        scope = await asyncio.to_thread(metering.project_scope, request.project_id)
        with metering.scoped(scope):
            try:
                answer = await self._provider.complete_json(  # type: ignore[attr-defined]
                    provider_id=request.provider_id,
                    model_id=request.model_id,
                    system=request.system,
                    user=request.user,
                )
            except Exception as error:
                return StoryAssistOutput(code=_safe_failure_code(error))  # type: ignore[arg-type]
        fields = ("title", "reason", "text")
        if not isinstance(answer, dict) or not all(
            isinstance(answer.get(key), str) for key in fields
        ):
            return StoryAssistOutput(code="invalid_provider_output")
        return StoryAssistOutput(
            title=answer["title"], reason=answer["reason"], text=answer["text"]
        )
