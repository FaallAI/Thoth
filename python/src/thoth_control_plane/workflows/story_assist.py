"""One Story Assist call as a short workflow the API waits on (spec 2026-10-27, 7)."""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from thoth_control_plane.activities.prompt_proposal import PROMPT_PROPOSAL_TASK_QUEUE
from thoth_control_plane.activities.story_assist import StoryAssistActivity
from thoth_control_plane.domain.story_assist import StoryAssistInput, StoryAssistOutput


@workflow.defn
class StoryAssistWorkflow:
    """No retry: a person is waiting, and the activity reports failures as codes."""

    @workflow.run
    async def run(self, request: StoryAssistInput) -> StoryAssistOutput:
        result: StoryAssistOutput = await workflow.execute_activity(
            StoryAssistActivity.run,
            request,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=1),
            task_queue=PROMPT_PROPOSAL_TASK_QUEUE,
        )
        return StoryAssistOutput.model_validate(result.model_dump(mode="json"))
