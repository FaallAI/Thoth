"""Every mapped activity runs in its workflow's step scope (spec 2026-10-25, G2).

Unlike the meter scope this interceptor makes no network call: the activity type alone
names the stage, and `activity.info()` carries the workflow id and the attempt.
"""

from __future__ import annotations

from typing import Any

from temporalio import activity
from temporalio.worker import ActivityInboundInterceptor, ExecuteActivityInput, Interceptor

from thoth_control_plane import progress
from thoth_control_plane.progress import StepScope

#: The activity type names the stage whose steps the activity records (spec G2).
STAGE_OF_ACTIVITY: dict[str, str] = {
    "inspect_source_candidates": "source",
    "attribute_source": "attribution",
    "build_footage": "footage",
    "assemble_content": "assembly",
}


class _ScopedActivity(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        info = activity.info()
        stage = STAGE_OF_ACTIVITY.get(info.activity_type)
        if stage is None:
            return await super().execute_activity(input)
        with progress.scoped(StepScope(info.workflow_id, stage, info.attempt)):
            return await super().execute_activity(input)


class ProgressScopeInterceptor(Interceptor):
    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _ScopedActivity(next)
