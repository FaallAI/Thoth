"""Steps served per run, and current_step filled on the live summary (spec G3, D6)."""

from datetime import UTC, datetime

import pytest

from thoth_control_plane.application.workflow_runs import WorkflowRunService
from thoth_control_plane.application.workflows import WorkflowNotFound
from thoth_control_plane.domain import Actor
from thoth_control_plane.domain.models import StageSummary, WorkflowStep, WorkflowSummary
from thoth_control_plane.domain.workflow_runs import StoredRun

ACTOR = Actor(actor_id="ws_a", actor_type="user")
FOREIGN = Actor(actor_id="ws_b", actor_type="user")
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


def a_step(seq: int, **overrides) -> WorkflowStep:
    values: dict = dict(
        seq=seq, stage="source", attempt=1, at=NOW, kind="info", code="source.read_link"
    )
    values.update(overrides)
    return WorkflowStep(**values)


def a_summary() -> WorkflowSummary:
    return WorkflowSummary(
        workflow_id="wf_1",
        status="running",
        created_at=NOW,
        updated_at=NOW,
        source={"display_url": "https://x.test/v", "platform": "tiktok"},
        stages=[
            StageSummary(id="source", label="Source", status="running"),
            StageSummary(id="approval", label="Approval", status="waiting"),
            StageSummary(id="attribution", label="Attribution", status="queued"),
            StageSummary(
                id="assembly", label="Assembly", status="skipped", skip_reason="assembly_off"
            ),
        ],
    )


def a_run(owner: Actor = ACTOR) -> StoredRun:
    return StoredRun(
        workflow_id="wf_1",
        project_id=None,
        actor_type=owner.actor_type,
        actor_id=owner.actor_id,
        display_url="https://x.test/v",
        platform="tiktok",
        status="running",
        history_expired=False,
        summary=None,
        created_at=NOW,
        updated_at=NOW,
    )


class Workflows:
    def __init__(self, summary: WorkflowSummary) -> None:
        self.summary = summary

    async def get(self, workflow_id: str, *, actor: Actor) -> WorkflowSummary:
        return self.summary


class Runs:
    def __init__(self, run: StoredRun | None) -> None:
        self.run, self.settled = run, []

    def get(self, workflow_id: str) -> StoredRun | None:
        return self.run

    def settle(self, workflow_id: str, *, status, summary, history_expired) -> None:
        self.settled.append(summary)


class Steps:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.paged: list[tuple[str, int, int]] = []

    def page(self, workflow_id: str, after: int, limit: int) -> list[WorkflowStep]:
        if self.fail:
            raise RuntimeError("step store down")
        self.paged.append((workflow_id, after, limit))
        return [a_step(1), a_step(2, code="source.fetch_post")]

    def current_steps(self, workflow_id: str) -> dict[str, WorkflowStep]:
        if self.fail:
            raise RuntimeError("step store down")
        return {"source": a_step(7, code="source.download_media", kind="progress", n=2, total=9)}


def service(runs=None, workflows=None, steps=None) -> WorkflowRunService:
    return WorkflowRunService(runs, None, workflows, None, None, steps=steps)


async def test_the_steps_page_serves_the_store_in_order() -> None:
    steps = Steps()
    page = await service(runs=Runs(a_run()), workflows=Workflows(a_summary()), steps=steps).steps(
        "wf_1", actor=ACTOR, after=5, limit=20
    )
    assert steps.paged == [("wf_1", 5, 20)]
    assert [step.code for step in page.steps] == ["source.read_link", "source.fetch_post"]


async def test_a_foreign_or_missing_run_is_not_found() -> None:
    steps = Steps()
    with pytest.raises(WorkflowNotFound):
        await service(runs=Runs(None), steps=steps).steps("wf_1", actor=ACTOR, after=0, limit=200)
    with pytest.raises(WorkflowNotFound):
        await service(runs=Runs(a_run(FOREIGN)), steps=steps).steps(
            "wf_1", actor=ACTOR, after=0, limit=200
        )
    assert steps.paged == []


async def test_without_a_run_store_or_a_step_store_the_page_is_empty() -> None:
    empty = await service(runs=None, steps=Steps()).steps("wf_1", actor=ACTOR, after=0, limit=200)
    assert empty.steps == []
    degraded = await service(runs=Runs(a_run()), steps=None).steps(
        "wf_1", actor=ACTOR, after=0, limit=200
    )
    assert degraded.steps == []
    with pytest.raises(WorkflowNotFound):  # an owner check still applies without a step store
        await service(runs=Runs(a_run(FOREIGN)), steps=None).steps(
            "wf_1", actor=ACTOR, after=0, limit=200
        )


async def test_current_step_fills_only_running_or_waiting_stages_after_settle() -> None:
    runs, steps = Runs(a_run()), Steps()
    summary = await service(runs=runs, workflows=Workflows(a_summary()), steps=steps).get(
        "wf_1", actor=ACTOR
    )
    by_id = {stage.id: stage for stage in summary.stages}
    assert by_id["source"].current_step is not None
    assert by_id["source"].current_step.code == "source.download_media"
    assert by_id["approval"].current_step is None  # waiting, but no step of that stage exists
    assert by_id["attribution"].current_step is None  # queued: never filled
    assert by_id["assembly"].current_step is None  # skipped: never filled
    assert all(stage.current_step is None for stage in runs.settled[0].stages)


async def test_a_step_store_error_still_returns_the_summary() -> None:
    runs = Runs(a_run())
    summary = await service(
        runs=runs, workflows=Workflows(a_summary()), steps=Steps(fail=True)
    ).get("wf_1", actor=ACTOR)
    assert all(stage.current_step is None for stage in summary.stages)
    assert runs.settled  # the settle itself still happened


async def test_no_step_store_leaves_the_summary_untouched() -> None:
    summary = await service(runs=Runs(a_run()), workflows=Workflows(a_summary())).get(
        "wf_1", actor=ACTOR
    )
    assert all(stage.current_step is None for stage in summary.stages)
