"""The estimate math over stored summaries, pure (run-progress spec G4, plan D1)."""

from datetime import UTC, datetime, timedelta

import pytest

from thoth_control_plane.application.estimates import estimate_seconds_remaining
from thoth_control_plane.domain.models import StageSummary, WorkflowStep, WorkflowSummary

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)
T0 = NOW - timedelta(hours=2)
PLANNED = ("approval", "source", "attribution", "footage", "assembly")


def stage(
    stage_id: str,
    status: str,
    *,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    current_step: WorkflowStep | None = None,
) -> StageSummary:
    return StageSummary(
        id=stage_id,
        label=stage_id.title(),
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        current_step=current_step,
    )


def live(status: str, stages: list[StageSummary]) -> WorkflowSummary:
    return WorkflowSummary(
        workflow_id="wf_live",
        status=status,
        created_at=T0,
        updated_at=NOW,
        source={"display_url": "https://x.test/v", "platform": "tiktok"},
        stages=stages,
    )


def succeeded(workflow_id: str, durations: dict[str, float | None]) -> WorkflowSummary:
    """One stored succeeded run. A stage mapped to a number ran that long; None means a
    pre-phase-1 summary whose completed stage carries no timestamps; a missing key means
    the stage never ran (skipped)."""
    stages = [
        stage(
            stage_id,
            "skipped" if stage_id not in durations else "completed",
            started_at=None if durations.get(stage_id) is None else T0,
            finished_at=(
                None
                if durations.get(stage_id) is None
                else T0 + timedelta(seconds=durations[stage_id])
            ),
        )
        for stage_id in PLANNED
    ]
    return WorkflowSummary(
        workflow_id=workflow_id,
        status="succeeded",
        created_at=T0,
        updated_at=NOW,
        source={"display_url": "https://x.test/v", "platform": "tiktok"},
        stages=stages,
    )


def wait_step(seconds_left: float) -> WorkflowStep:
    return WorkflowStep(
        seq=5,
        stage="source",
        attempt=1,
        at=NOW,
        kind="wait",
        code="source.page_gap",
        wait_until=NOW + timedelta(seconds=seconds_left),
    )


def test_below_five_succeeded_histories_has_no_estimate() -> None:
    history = [succeeded(f"wf_{n}", {"source": 180.0}) for n in range(4)]
    run = live("running", [stage("source", "running", started_at=NOW)])
    assert estimate_seconds_remaining(run, history, NOW) is None


def test_the_median_of_an_odd_history_count_is_the_middle_value() -> None:
    history = [
        succeeded(f"wf_{n}", {"source": float(seconds), "approval": 9_999.0})
        for n, seconds in enumerate((100, 200, 300, 400, 500))
    ]
    run = live(
        "running",
        [
            stage("source", "running", started_at=NOW),
            stage("approval", "waiting"),
            stage("attribution", "completed", started_at=T0, finished_at=T0),
        ],
    )
    # The approval stage never counts, whatever its own history measured.
    assert estimate_seconds_remaining(run, history, NOW) == 300


def test_the_median_of_an_even_history_count_averages_the_middle_pair() -> None:
    history = [
        succeeded(f"wf_{n}", {"source": float(seconds)})
        for n, seconds in enumerate((100, 200, 300, 400, 500, 600))
    ]
    run = live("running", [stage("source", "running", started_at=NOW)])
    assert estimate_seconds_remaining(run, history, NOW) == 350


def test_a_stage_without_a_median_falls_back_to_the_spec_default() -> None:
    history = [succeeded(f"wf_{n}", {"source": 180.0}) for n in range(5)]
    run = live(
        "running",
        [
            stage("source", "completed", started_at=T0, finished_at=T0),
            stage("footage", "queued"),
        ],
    )
    assert estimate_seconds_remaining(run, history, NOW) == 240


def test_a_queued_run_sums_every_planned_stage() -> None:
    history = [succeeded(f"wf_{n}", {"source": 180.0, "footage": 60.0}) for n in range(5)]
    run = live("queued", [stage(stage_id, "queued") for stage_id in PLANNED])
    # source median 180 + attribution default 60 + footage median 60 + assembly default 60.
    assert estimate_seconds_remaining(run, history, NOW) == 360


def test_a_running_stage_past_its_median_estimates_zero() -> None:
    history = [succeeded(f"wf_{n}", {"source": 180.0}) for n in range(5)]
    run = live("running", [stage("source", "running", started_at=NOW - timedelta(seconds=600))])
    assert estimate_seconds_remaining(run, history, NOW) == 0


def test_a_wait_step_extends_the_remaining_time() -> None:
    history = [succeeded(f"wf_{n}", {"source": 180.0}) for n in range(5)]
    started = NOW - timedelta(seconds=170)  # median minus elapsed: 10 s

    held = live(
        "running",
        [stage("source", "running", started_at=started, current_step=wait_step(90))],
    )
    assert estimate_seconds_remaining(held, history, NOW) == 90

    brief = live(
        "running",
        [stage("source", "running", started_at=started, current_step=wait_step(5))],
    )
    assert estimate_seconds_remaining(brief, history, NOW) == 10


@pytest.mark.parametrize("status", ["awaiting_approval", "succeeded", "failed", "cancelled"])
def test_only_running_and_queued_runs_get_an_estimate(status: str) -> None:
    history = [succeeded(f"wf_{n}", {"source": 180.0}) for n in range(5)]
    run = live(status, [stage("source", "running", started_at=NOW)])
    assert estimate_seconds_remaining(run, history, NOW) is None


def test_histories_without_stage_timestamps_do_not_count_toward_the_minimum() -> None:
    """Runs from before phase 1 carry no stage timestamps: hundreds of them must not
    turn the estimate on, or the UI shows a number built from defaults (DESIGN 7.3)."""
    untimed = [succeeded(f"wf_old_{n}", {"source": None}) for n in range(20)]
    timed = [
        succeeded("wf_0", {"source": 100.0}),
        succeeded("wf_1", {"source": 200.0}),
        succeeded("wf_2", {"source": 300.0}),
    ]
    run = live("running", [stage("source", "running", started_at=NOW)])
    assert estimate_seconds_remaining(run, untimed + timed, NOW) is None

    timed += [succeeded("wf_3", {"source": 200.0}), succeeded("wf_4", {"source": 200.0})]
    assert estimate_seconds_remaining(run, untimed + timed, NOW) == 200
