"""The inbox settles an actor's stale rows at most once per window (review N3).

Each settle asks Temporal about up to `SETTLE_LIMIT` rows, so a client that polls the
inbox every second must not turn into a Temporal call storm.
"""

from datetime import UTC, datetime

import pytest

from thoth_control_plane.application.workflow_runs import (
    INBOX_SETTLE_SECONDS,
    WorkflowRunService,
)
from thoth_control_plane.application.workflows import WorkflowService
from thoth_control_plane.domain import Actor
from thoth_control_plane.domain.workflow_runs import StoredRun

ACTOR = Actor(actor_id="ws_one", actor_type="user")
OTHER = Actor(actor_id="ws_two", actor_type="user")
NOW = datetime(2026, 10, 26, tzinfo=UTC)


def stale(workflow_id: str, actor: Actor) -> StoredRun:
    return StoredRun(
        workflow_id=workflow_id,
        project_id=None,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        display_url="https://x.test/v",
        platform="tiktok",
        status="running",
        history_expired=False,
        summary=None,
        created_at=NOW,
        updated_at=NOW,
    )


class Runs:
    def unsettled(self, actor: Actor, limit: int) -> list[StoredRun]:
        return [stale(f"wf_{actor.actor_id}", actor)]

    def awaiting_approval(self, actor: Actor, limit: int) -> list[StoredRun]:
        return []

    def unacknowledged_failures(self, actor: Actor, limit: int) -> list[StoredRun]:
        return []


class Gateway:
    def __init__(self) -> None:
        self.settled: list[str] = []

    async def settle(self, workflow_id: str):
        self.settled.append(workflow_id)
        raise RuntimeError("temporal unavailable")  # the row is kept as it is


@pytest.mark.asyncio
async def test_inbox_polls_settle_once_per_window_per_actor() -> None:
    gateway = Gateway()
    times = [0.0]
    service = WorkflowRunService(
        Runs(), None, WorkflowService(gateway), gateway, monotonic=lambda: times[0]
    )

    await service.inbox(actor=ACTOR)
    times[0] = INBOX_SETTLE_SECONDS - 1
    await service.inbox(actor=ACTOR)  # a fast poll reads rows but asks Temporal nothing
    await service.inbox(actor=OTHER)  # another actor has its own window
    assert gateway.settled == ["wf_ws_one", "wf_ws_two"]

    times[0] = INBOX_SETTLE_SECONDS + 1
    await service.inbox(actor=ACTOR)
    assert gateway.settled == ["wf_ws_one", "wf_ws_two", "wf_ws_one"]
