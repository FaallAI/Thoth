"""Estimate wiring: filled after the current steps, never stored, cached, error-safe (D2)."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from tests.conftest import InMemoryWorkflowGateway
from tests.sqlite_support import sqlite_engine
from thoth_control_plane.application.ports import WorkflowRunsUnavailable
from thoth_control_plane.application.workflow_runs import WorkflowRunService
from thoth_control_plane.application.workflows import WorkflowService
from thoth_control_plane.domain import Actor
from thoth_control_plane.domain.models import StageSummary, WorkflowSummary
from thoth_control_plane.infrastructure import (
    run_models,  # noqa: F401  (workflow_runs rows)
    step_models,  # noqa: F401  (workflow_steps rows)
)
from thoth_control_plane.infrastructure.source_account_models import Base
from thoth_control_plane.infrastructure.step_store import StepStore
from thoth_control_plane.infrastructure.workflow_run_store import WorkflowRunStore
from thoth_control_plane.progress import StepRecord, StepScope

ACTOR = Actor(actor_id="ws_one", actor_type="user")


def succeeded(workflow_id: str, *, updated_at: datetime) -> WorkflowSummary:
    started = updated_at - timedelta(hours=1)
    return WorkflowSummary(
        workflow_id=workflow_id,
        status="succeeded",
        created_at=started,
        updated_at=updated_at,
        source={"display_url": "https://x.test/v", "platform": "tiktok"},
        stages=[
            StageSummary(
                id="source",
                label="Source",
                status="completed",
                started_at=started,
                finished_at=started + timedelta(seconds=30),
            )
        ],
    )


def live_running(started_at: datetime) -> WorkflowSummary:
    now = started_at
    return WorkflowSummary(
        workflow_id="wf_live",
        status="running",
        created_at=now - timedelta(hours=1),
        updated_at=now,
        source={"display_url": "https://x.test/v", "platform": "tiktok"},
        stages=[
            StageSummary(id="source", label="Source", status="running", started_at=started_at),
            StageSummary(id="approval", label="Approval", status="waiting"),
            StageSummary(
                id="assembly",
                label="Assembly",
                status="completed",
                started_at=started_at,
                finished_at=now,
            ),
        ],
    )


@pytest_asyncio.fixture
async def engine():
    engine = sqlite_engine()
    Base.metadata.create_all(engine)
    return engine


def seed_histories(runs: WorkflowRunStore, count: int = 5) -> None:
    now = datetime.now(UTC)
    for n in range(count):
        runs.record_start(succeeded(f"wf_hist_{n}", updated_at=now), project_id=None, actor=ACTOR)
        runs.settle(
            f"wf_hist_{n}",
            status="succeeded",
            summary=succeeded(f"wf_hist_{n}", updated_at=now - timedelta(minutes=n)),
            history_expired=False,
        )


def gateway_with_live(started_at: datetime) -> InMemoryWorkflowGateway:
    gateway = InMemoryWorkflowGateway()
    gateway.workflows["wf_live"] = live_running(started_at)
    gateway.owners["wf_live"] = (ACTOR.actor_type, ACTOR.actor_id)
    return gateway


@pytest.mark.asyncio
async def test_the_estimate_is_filled_after_the_current_step(engine) -> None:
    runs = WorkflowRunStore(engine)
    steps = StepStore(engine)
    seed_histories(runs)
    now = datetime.now(UTC)
    gateway = gateway_with_live(now)
    steps.append(
        StepScope("wf_live", "source", 1),
        StepRecord(
            at=now,
            kind="wait",
            code="source.page_gap",
            wait_until=now + timedelta(seconds=90),
        ),
    )
    service = WorkflowRunService(runs, None, WorkflowService(gateway), gateway, steps=steps)

    detail = await service.get("wf_live", actor=ACTOR)

    source = detail.stages[0]
    assert source.current_step is not None and source.current_step.code == "source.page_gap"
    # The wait step (90 s) outranks the 30 s median, so the estimate must have seen it.
    assert detail.estimate_seconds_remaining == 90


@pytest.mark.asyncio
async def test_settle_never_receives_the_estimate(engine) -> None:
    class RecordingRuns(WorkflowRunStore):
        def __init__(self, engine) -> None:
            super().__init__(engine)
            self.settled: list[WorkflowSummary | None] = []

        def settle(self, workflow_id, *, status, summary, history_expired) -> None:
            self.settled.append(summary)
            super().settle(
                workflow_id, status=status, summary=summary, history_expired=history_expired
            )

    runs = RecordingRuns(engine)
    seed_histories(runs)
    now = datetime.now(UTC)
    gateway = gateway_with_live(now)
    runs.record_start(live_running(now), project_id=None, actor=ACTOR)
    service = WorkflowRunService(runs, None, WorkflowService(gateway), gateway)

    detail = await service.get("wf_live", actor=ACTOR)

    assert detail.estimate_seconds_remaining is not None
    assert all(s is None or s.estimate_seconds_remaining is None for s in runs.settled)
    stored = runs.get("wf_live")
    assert stored is not None and stored.summary is not None
    assert stored.summary.estimate_seconds_remaining is None


class HistoryRuns:
    """The run-store surface `get` touches, with a counting `recent_succeeded`."""

    def __init__(self, histories: list[WorkflowSummary]) -> None:
        self.histories = histories
        self.calls = 0

    def settle(self, workflow_id, *, status, summary, history_expired) -> None: ...

    def recent_succeeded(
        self, actor: Actor, platform: str, limit: int = 20
    ) -> list[WorkflowSummary]:
        self.calls += 1
        return self.histories


@pytest.mark.asyncio
async def test_the_history_cache_hits_within_sixty_seconds() -> None:
    now = datetime.now(UTC)
    gateway = gateway_with_live(now)
    histories = [succeeded(f"wf_hist_{n}", updated_at=now) for n in range(5)]
    runs = HistoryRuns(histories)
    times = [0.0]
    service = WorkflowRunService(
        runs, None, WorkflowService(gateway), gateway, monotonic=lambda: times[0]
    )

    await service.get("wf_live", actor=ACTOR)
    await service.get("wf_live", actor=ACTOR)
    assert runs.calls == 1  # the dashboard polls every second; one store hit per minute

    times[0] = 61.0
    await service.get("wf_live", actor=ACTOR)
    assert runs.calls == 2


@pytest.mark.asyncio
async def test_a_history_store_error_still_returns_the_summary() -> None:
    now = datetime.now(UTC)
    gateway = gateway_with_live(now)

    class FailingRuns(HistoryRuns):
        def recent_succeeded(self, actor: Actor, platform: str, limit: int = 20):
            raise WorkflowRunsUnavailable("workflow_runs_unavailable")

    service = WorkflowRunService(FailingRuns([]), None, WorkflowService(gateway), gateway)

    detail = await service.get("wf_live", actor=ACTOR)

    assert detail.workflow_id == "wf_live"
    assert detail.estimate_seconds_remaining is None


@pytest.mark.asyncio
async def test_without_a_run_store_the_summary_still_serves() -> None:
    gateway = gateway_with_live(datetime.now(UTC))
    service = WorkflowRunService(None, None, WorkflowService(gateway), gateway)

    detail = await service.get("wf_live", actor=ACTOR)

    assert detail.workflow_id == "wf_live"
    assert detail.estimate_seconds_remaining is None
