"""Starts a draft's narration workflow, signals its decision, and starts one beat's re-voice."""

from __future__ import annotations

from temporalio.client import Client

from thoth_control_plane.application.narrations import NarrationUnavailable, revoice_workflow_id
from thoth_control_plane.domain.narration import (
    NarrationDecision,
    NarrationRevoiceInput,
    NarrationStepInput,
)
from thoth_control_plane.infrastructure.temporal_gateway import TASK_QUEUE


class TemporalNarrationGateway:
    def __init__(self, client: Client) -> None:
        self._client = client

    async def start(self, workflow_id: str, step: NarrationStepInput) -> None:
        try:
            await self._client.start_workflow(
                "NarrationWorkflow", step, id=workflow_id, task_queue=TASK_QUEUE
            )
        except Exception as error:
            raise NarrationUnavailable() from error

    async def decide(self, workflow_id: str, decision: NarrationDecision) -> None:
        try:
            await self._client.get_workflow_handle(workflow_id).signal("decide", decision)
        except Exception as error:
            raise NarrationUnavailable() from error

    async def cancel(self, workflow_id: str) -> None:
        try:
            await self._client.get_workflow_handle(workflow_id).signal("cancel")
        except Exception as error:
            raise NarrationUnavailable() from error

    async def revoice(self, step: NarrationRevoiceInput) -> None:
        try:
            await self._client.start_workflow(
                "NarrationRevoiceWorkflow",
                step,
                id=revoice_workflow_id(step),
                task_queue=TASK_QUEUE,
            )
        except Exception as error:
            raise NarrationUnavailable() from error
