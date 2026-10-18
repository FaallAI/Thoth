"""Settling a run from Temporal describe and result, without the owner query (ruling P4)."""

import json
from datetime import UTC, datetime

import pytest
from temporalio.client import WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from thoth_control_plane.application.ports import RunClosed, RunExpired, RunLive
from thoth_control_plane.domain import WorkflowSummary
from thoth_control_plane.infrastructure.temporal_gateway import TemporalWorkflowGateway

T0 = datetime(2026, 10, 18, tzinfo=UTC).isoformat()
SUMMARY = WorkflowSummary.model_validate_json(
    json.dumps(
        {
            "workflow_id": "wf_a",
            "status": "succeeded",
            "created_at": T0,
            "updated_at": T0,
            "source": {"display_url": "https://example.test/p", "platform": "example"},
            "stages": [],
        }
    )
)


class Handle:
    def __init__(self, status=None, error=None):
        self.id = "wf_a"
        self._status = status
        self._error = error

    async def describe(self):
        if self._error:
            raise self._error
        return type("Description", (), {"status": self._status})()

    async def result(self):
        return SUMMARY

    async def query(self, query):
        return SUMMARY.model_copy(update={"status": "running"})


class Client:
    def __init__(self, handle):
        self.handle = handle

    def get_workflow_handle(self, workflow_id, *, result_type=None):
        return self.handle


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handle", "expected"),
    [
        (Handle(WorkflowExecutionStatus.RUNNING), RunLive),
        (Handle(WorkflowExecutionStatus.COMPLETED), RunClosed),
        (Handle(error=RPCError("gone", RPCStatusCode.NOT_FOUND, b"")), RunExpired),
    ],
)
async def test_settle_maps_each_execution_state(handle, expected) -> None:
    outcome = await TemporalWorkflowGateway(Client(handle)).settle("wf_a")
    assert isinstance(outcome, expected)


@pytest.mark.asyncio
async def test_completed_reports_the_returned_summary_and_terminal_states_map() -> None:
    gateway = TemporalWorkflowGateway(Client(Handle(WorkflowExecutionStatus.COMPLETED)))
    assert await gateway.settle("wf_a") == RunClosed(SUMMARY, "succeeded")
    terminated = TemporalWorkflowGateway(Client(Handle(WorkflowExecutionStatus.TERMINATED)))
    assert await terminated.settle("wf_a") == RunClosed(None, "failed")
    cancelled = TemporalWorkflowGateway(Client(Handle(WorkflowExecutionStatus.CANCELED)))
    assert await cancelled.settle("wf_a") == RunClosed(None, "cancelled")


@pytest.mark.asyncio
async def test_another_rpc_error_is_not_ready() -> None:
    from thoth_control_plane.application import WorkflowNotReady

    down = Handle(error=RPCError("down", RPCStatusCode.UNAVAILABLE, b""))
    with pytest.raises(WorkflowNotReady):
        await TemporalWorkflowGateway(Client(down)).settle("wf_a")
