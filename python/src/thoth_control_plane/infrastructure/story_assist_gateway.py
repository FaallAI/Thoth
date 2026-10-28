"""Runs one Story Assist workflow and waits for it (spec 2026-10-27, 7)."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from temporalio.client import Client

from thoth_control_plane.activities.prompt_proposal import PROMPT_PROPOSAL_TASK_QUEUE
from thoth_control_plane.application.story_assist import StoryAssistUnavailable
from thoth_control_plane.domain.story_assist import StoryAssistInput, StoryAssistOutput


class TemporalStoryAssistGateway:
    def __init__(self, client: Client) -> None:
        self._client = client

    async def complete(self, request: StoryAssistInput) -> StoryAssistOutput:
        try:
            result = await self._client.execute_workflow(
                "StoryAssistWorkflow",
                request,
                id=f"story-assist/{uuid4().hex}",
                task_queue=PROMPT_PROPOSAL_TASK_QUEUE,
                execution_timeout=timedelta(seconds=75),
                result_type=StoryAssistOutput,
            )
        except Exception as error:
            raise StoryAssistUnavailable() from error
        return StoryAssistOutput.model_validate(result)
