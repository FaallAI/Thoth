"""Workflow starts consume the plan allowance (spec 2026-10-20 billing, 1.3-1.4)."""

import pytest

from thoth_control_plane.application.workflow_runs import WorkflowRunService
from thoth_control_plane.billing import PlanLimitReached, workflow_ref
from thoth_control_plane.domain import Actor

ACTOR = Actor(actor_id="ws_a", actor_type="user")


class Billing:
    def __init__(self, allowance: int = 1) -> None:
        self.allowance, self.uses, self.released = allowance, set(), []

    def consume(self, workspace_id, kind, ref):
        if ref in self.uses:
            return False
        if len(self.uses) >= self.allowance:
            raise PlanLimitReached(kind, len(self.uses), self.allowance, None)
        self.uses.add(ref)
        return True

    def release(self, workspace_id, kind, ref):
        self.released.append(ref)
        self.uses.discard(ref)


class Workflows:
    def __init__(self, fail: Exception | None = None) -> None:
        self.fail, self.started = fail, 0

    async def start(self, request, *, actor, idempotency_key):
        if self.fail is not None:
            raise self.fail
        self.started += 1
        return object()


async def test_a_start_past_the_allowance_never_reaches_temporal() -> None:
    workflows, billing = Workflows(), Billing(allowance=1)
    service = WorkflowRunService(None, None, workflows, None, billing)
    await service.start(None, object(), actor=ACTOR, idempotency_key="k1")
    with pytest.raises(PlanLimitReached):
        await service.start(None, object(), actor=ACTOR, idempotency_key="k2")
    assert workflows.started == 1


async def test_a_retry_with_the_same_key_is_admitted_without_a_second_unit() -> None:
    workflows, billing = Workflows(), Billing(allowance=1)
    service = WorkflowRunService(None, None, workflows, None, billing)
    await service.start(None, object(), actor=ACTOR, idempotency_key="k1")
    await service.start(None, object(), actor=ACTOR, idempotency_key="k1")
    assert workflows.started == 2 and len(billing.uses) == 1


async def test_a_failed_start_gives_its_unit_back_but_a_retry_never_releases_the_first() -> None:
    billing = Billing(allowance=1)
    with pytest.raises(RuntimeError):
        await WorkflowRunService(None, None, Workflows(RuntimeError()), None, billing).start(
            None, object(), actor=ACTOR, idempotency_key="k1"
        )
    assert billing.released == [workflow_ref("user", "ws_a", "k1")]
    ok = WorkflowRunService(None, None, Workflows(), None, billing)
    await ok.start(None, object(), actor=ACTOR, idempotency_key="k2")
    with pytest.raises(RuntimeError):  # same key, conflicting payload: not a fresh unit
        await WorkflowRunService(None, None, Workflows(RuntimeError()), None, billing).start(
            None, object(), actor=ACTOR, idempotency_key="k2"
        )
    assert workflow_ref("user", "ws_a", "k2") in billing.uses
