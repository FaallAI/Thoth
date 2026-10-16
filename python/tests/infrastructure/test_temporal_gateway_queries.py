"""A query the worker fails to answer (a TMPRL1101 stall) is "not ready, retry", never a 500."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from temporalio.client import WorkflowQueryFailedError

from thoth_control_plane.application import WorkflowNotReady
from thoth_control_plane.domain import Actor
from thoth_control_plane.infrastructure.temporal_gateway import TemporalWorkflowGateway


class _StalledHandle:
    id = "wf_stalled"

    async def query(self, *args: Any, **kwargs: Any) -> Any:
        raise WorkflowQueryFailedError(
            "[TMPRL1101] Potential deadlock detected: workflow didn't yield within 2 second(s)."
        )


class _Client:
    def get_workflow_handle(self, workflow_id: str) -> _StalledHandle:
        return _StalledHandle()


async def test_a_failed_query_is_not_ready_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    gateway = TemporalWorkflowGateway(_Client())  # type: ignore[arg-type]
    actor = Actor(actor_id="owner", actor_type="user")

    with caplog.at_level(logging.WARNING), pytest.raises(WorkflowNotReady):
        await gateway.get("wf_stalled", actor=actor)

    assert "TMPRL1101" in caplog.text
