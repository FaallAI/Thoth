"""The real gateway refuses a workflow whose owner is another workspace's actor."""

import pytest

from thoth_control_plane.application import WorkflowNotFound
from thoth_control_plane.domain.models import Actor, ActorSnapshot
from thoth_control_plane.infrastructure.temporal_gateway import TemporalWorkflowGateway
from thoth_control_plane.workflows.source_investigation import SourceInvestigationWorkflow

SUMMARY = object()


class Handle:
    id = "wf_x"

    def __init__(self, owner: ActorSnapshot) -> None:
        self.owner = owner

    async def query(self, query):
        return self.owner if query == SourceInvestigationWorkflow.owner_actor else SUMMARY


class Client:
    def __init__(self, owner: ActorSnapshot) -> None:
        self.handle = Handle(owner)

    def get_workflow_handle(self, workflow_id: str) -> Handle:
        return self.handle


@pytest.mark.asyncio
async def test_a_workflow_of_another_workspace_is_not_found() -> None:
    gateway = TemporalWorkflowGateway(Client(ActorSnapshot(actor_id="owner", actor_type="user")))
    with pytest.raises(WorkflowNotFound):
        await gateway.get("wf_x", actor=Actor(actor_id="ws_abc", actor_type="user"))
    assert await gateway.get("wf_x", actor=Actor(actor_id="owner", actor_type="user")) is SUMMARY
