"""Every activity runs in its workflow's meter scope (spec 2026-10-20 metering, 2.2).

The gateway writes the workspace into the workflow memo when it starts the workflow, so the
scope is right even when the first activity runs before the `workflow_runs` row is written.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from temporalio import activity
from temporalio.worker import ActivityInboundInterceptor, ExecuteActivityInput, Interceptor

from thoth_control_plane import metering

logger = logging.getLogger(__name__)


async def _memo_workspace(client: Any, workflow_id: str) -> str | None:
    try:
        description = await client.get_workflow_handle(workflow_id).describe()
        workspace = (await description.memo()).get("workspace_id")
    except Exception:
        logger.warning("workflow memo unavailable; the meter scope falls back")
        return None
    return workspace if isinstance(workspace, str) else None


class _ScopedActivity(ActivityInboundInterceptor):
    def __init__(self, next: ActivityInboundInterceptor, client: Any) -> None:
        super().__init__(next)
        self._client = client

    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        workflow_id = activity.info().workflow_id
        memo = await _memo_workspace(self._client, workflow_id)
        scope = await asyncio.to_thread(metering.workflow_scope, workflow_id, memo)
        with metering.scoped(scope):
            return await super().execute_activity(input)


class MeterScopeInterceptor(Interceptor):
    def __init__(self, client: Any) -> None:
        self._client = client

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _ScopedActivity(next, self._client)
