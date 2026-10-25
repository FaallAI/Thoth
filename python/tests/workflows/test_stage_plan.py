"""Pure tests for the stage plan (spec 2026-10-25, G1, D1-D3, D5)."""

from datetime import UTC, datetime, timedelta

import pytest

from thoth_control_plane.workflows.stage_plan import StagePlan, build_plan

T0 = datetime(2026, 10, 25, 8, 0, 0, tzinfo=UTC)
T1 = T0 + timedelta(seconds=30)
T2 = T1 + timedelta(seconds=30)
T3 = T2 + timedelta(seconds=30)
T4 = T3 + timedelta(seconds=30)


def plan_ids(plan: StagePlan) -> list[str]:
    return [stage.id for stage in plan.snapshot()]


def statuses(plan: StagePlan) -> dict[str, str]:
    return {stage.id: stage.status for stage in plan.snapshot()}


def reasons(plan: StagePlan) -> dict[str, str | None]:
    return {stage.id: stage.skip_reason for stage in plan.snapshot()}


def stage(plan: StagePlan, stage_id: str):
    return next(stage for stage in plan.snapshot() if stage.id == stage_id)


FLAG_COMBINATIONS = [
    (attribute, assemble, footage)
    for attribute in (False, True)
    for assemble in (False, True)
    for footage in (False, True)
]


@pytest.mark.parametrize(
    "attribute,assemble,footage", FLAG_COMBINATIONS, ids=[str(c) for c in FLAG_COMBINATIONS]
)
def test_produce_video_plans_every_flag_combination(
    attribute: bool, assemble: bool, footage: bool
) -> None:
    plan = build_plan(
        "produce_video",
        attribute_source=attribute,
        assemble_content=assemble,
        build_footage=footage,
    )
    assert plan_ids(plan) == ["source", "approval", "attribution", "footage", "assembly"]
    assert statuses(plan) == {
        "source": "queued",
        "approval": "queued",
        "attribution": "queued" if attribute else "skipped",
        "footage": "queued" if (assemble and footage) else "skipped",
        "assembly": "queued" if assemble else "skipped",
    }
    assert reasons(plan) == {
        "approval": None,
        "source": None,
        "attribution": None if attribute else "attribution_off",
        "footage": None if (assemble and footage) else "footage_off",
        "assembly": None if assemble else "assembly_off",
    }
    assert all(s.started_at is None and s.finished_at is None for s in plan.snapshot())


@pytest.mark.parametrize(
    "attribute,assemble,footage", FLAG_COMBINATIONS, ids=[str(c) for c in FLAG_COMBINATIONS]
)
def test_identify_original_plans_every_flag_combination(
    attribute: bool, assemble: bool, footage: bool
) -> None:
    plan = build_plan(
        "identify_original",
        attribute_source=attribute,
        assemble_content=assemble,
        build_footage=footage,
    )
    assert plan_ids(plan) == ["source", "attribution", "footage", "assembly"]
    assert statuses(plan) == {
        "source": "queued",
        "attribution": "queued" if attribute else "skipped",
        "footage": "queued" if (assemble and footage) else "skipped",
        "assembly": "queued" if assemble else "skipped",
    }
    assert reasons(plan) == {
        "source": None,
        "attribution": None if attribute else "attribution_off",
        "footage": None if (assemble and footage) else "footage_off",
        "assembly": None if assemble else "assembly_off",
    }


def test_build_plan_rejects_an_unknown_intent() -> None:
    with pytest.raises(ValueError):
        build_plan("make_coffee", attribute_source=False, assemble_content=False, build_footage=False)


def test_the_happy_path_records_ordered_timestamps() -> None:
    plan = build_plan(
        "produce_video", attribute_source=True, assemble_content=True, build_footage=True
    )
    plan.start("source", T0)
    plan.complete("source", T1)
    plan.wait("approval", T1)
    plan.complete("approval", T2)
    plan.start("attribution", T2)
    plan.complete("attribution", T3)
    plan.start("footage", T3)
    plan.complete("footage", T4)
    plan.start("assembly", T4)
    plan.complete("assembly", T4)

    assert statuses(plan) == {stage_id: "completed" for stage_id in plan_ids(plan)}
    for entry in plan.snapshot():
        assert entry.started_at is not None and entry.finished_at is not None
        assert entry.started_at <= entry.finished_at
    assert stage(plan, "source").started_at == T0
    assert stage(plan, "source").finished_at == T1
    assert stage(plan, "approval").started_at == T1  # the wait starts the approval stage
    assert stage(plan, "approval").finished_at == T2


def test_only_source_reports_progress_once_completed() -> None:
    plan = build_plan(
        "identify_original", attribute_source=True, assemble_content=True, build_footage=True
    )
    plan.start("source", T0)
    assert stage(plan, "source").progress is None
    plan.complete("source", T1)
    plan.start("attribution", T1)
    plan.complete("attribution", T2)

    assert stage(plan, "source").progress == 1.0
    assert stage(plan, "attribution").progress is None


def test_complete_is_idempotent_and_keeps_the_first_timestamp() -> None:
    plan = build_plan("identify_original", attribute_source=True, assemble_content=False, build_footage=False)
    plan.start("source", T0)
    plan.complete("source", T1)
    plan.complete("source", T2)

    source = stage(plan, "source")
    assert source.status == "completed"
    assert source.finished_at == T1


def test_fail_overrides_a_completed_stage_and_skips_the_rest() -> None:
    plan = build_plan("produce_video", attribute_source=True, assemble_content=True, build_footage=True)
    plan.start("source", T0)
    plan.complete("source", T1)
    plan.wait("approval", T1)
    plan.complete("approval", T2)
    plan.start("attribution", T2)
    plan.complete("attribution", T3)
    plan.start("footage", T3)

    plan.fail("footage", T4)
    plan.skip_queued("run_failed")

    assert statuses(plan) == {
        "source": "completed",
        "approval": "completed",
        "attribution": "completed",
        "footage": "failed",
        "assembly": "skipped",
    }
    assert stage(plan, "footage").finished_at == T4
    assert reasons(plan)["assembly"] == "run_failed"


def test_fail_overrides_a_stage_that_recorded_its_completion_event() -> None:
    # `_attribute`/`_assemble` record STAGE_COMPLETED before the workflow decides the run
    # failed, so `fail` must win over an earlier `complete`.
    plan = build_plan("identify_original", attribute_source=True, assemble_content=True, build_footage=True)
    plan.start("source", T0)
    plan.complete("source", T1)
    plan.start("assembly", T1)
    plan.complete("assembly", T2)

    plan.fail("assembly", T3)
    assert stage(plan, "assembly").status == "failed"
    assert stage(plan, "assembly").finished_at == T3


def test_cancel_open_cancels_the_open_stage_and_skips_the_queue() -> None:
    plan = build_plan("produce_video", attribute_source=True, assemble_content=True, build_footage=True)
    plan.start("source", T0)
    plan.complete("source", T1)
    plan.start("attribution", T1)

    plan.cancel_open(T2)

    assert statuses(plan) == {
        "source": "completed",
        "approval": "skipped",
        "attribution": "cancelled",
        "footage": "skipped",
        "assembly": "skipped",
    }
    assert stage(plan, "attribution").finished_at == T2
    assert reasons(plan)["approval"] == "run_cancelled"
    assert reasons(plan)["footage"] == "run_cancelled"
    assert reasons(plan)["assembly"] == "run_cancelled"


def test_cancel_open_cancels_a_waiting_stage() -> None:
    plan = build_plan("produce_video", attribute_source=True, assemble_content=False, build_footage=False)
    plan.start("source", T0)
    plan.complete("source", T1)
    plan.wait("approval", T1)

    plan.cancel_open(T2)

    assert stage(plan, "approval").status == "cancelled"
    assert stage(plan, "approval").started_at == T1
    assert stage(plan, "approval").finished_at == T2


def test_skip_queued_only_touches_queued_stages() -> None:
    plan = build_plan("identify_original", attribute_source=False, assemble_content=True, build_footage=False)
    plan.start("source", T0)
    plan.complete("source", T1)

    plan.skip_queued("legacy_source")

    assert statuses(plan) == {
        "source": "completed",
        "attribution": "skipped",
        "footage": "skipped",
        "assembly": "skipped",
    }
    assert reasons(plan) == {
        "source": None,
        "attribution": "attribution_off",  # the build-time reason is kept
        "footage": "footage_off",
        "assembly": "legacy_source",
    }


def test_transitions_never_resurrect_a_skipped_stage() -> None:
    plan = build_plan("identify_original", attribute_source=True, assemble_content=False, build_footage=False)
    plan.skip_queued("run_failed")

    plan.start("attribution", T0)
    plan.complete("attribution", T1)
    plan.wait("attribution", T1)
    plan.fail("attribution", T2)

    assert stage(plan, "attribution").status == "skipped"
    assert stage(plan, "attribution").skip_reason == "run_failed"
    assert stage(plan, "attribution").started_at is None
    assert stage(plan, "attribution").finished_at is None


def test_a_snapshot_returns_fresh_validated_stage_summaries() -> None:
    from thoth_control_plane.domain.models import StageSummary

    plan = build_plan("produce_video", attribute_source=True, assemble_content=True, build_footage=True)
    plan.start("source", T0)
    first = plan.snapshot()
    second = plan.snapshot()

    assert all(isinstance(stage, StageSummary) for stage in first)
    assert first == second
    assert first is not second


def test_unknown_stage_ids_raise() -> None:
    plan = build_plan("identify_original", attribute_source=False, assemble_content=False, build_footage=False)
    with pytest.raises(KeyError):
        plan.start("approval", T0)  # identify_original has no approval stage
    with pytest.raises(KeyError):
        plan.complete("narration", T0)
    with pytest.raises(KeyError):
        plan.wait("render", T0)
    with pytest.raises(KeyError):
        plan.fail("delivery", T0)


def test_labels_follow_the_design_table() -> None:
    plan = build_plan("produce_video", attribute_source=True, assemble_content=True, build_footage=True)
    labels = {stage.id: stage.label for stage in plan.snapshot()}
    assert labels == {
        "source": "Fetch the source",
        "approval": "Your review",
        "attribution": "Find the original",
        "footage": "Collect footage",
        "assembly": "Build the content set",
    }
