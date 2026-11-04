"""StageSummary contract tests for the run-progress stage plan (spec 2026-10-25, G1)."""

import json

import pytest
from pydantic import ValidationError

from thoth_control_plane.domain.models import StageSummary

# An old stored summary, exactly as written before the stage-plan fields existed.
OLD_STORED_SUMMARY = json.dumps(
    {
        "workflow_id": "wf_000000000000000000000001",
        "status": "succeeded",
        "created_at": "2026-08-28T08:00:00Z",
        "updated_at": "2026-08-28T08:01:00Z",
        "source": {"display_url": "https://www.tiktok.com/@c/video/1", "platform": "tiktok"},
        "stages": [
            {
                "id": "source",
                "label": "Investigate original source",
                "status": "completed",
                "progress": 1.0,
            }
        ],
    }
)


def test_the_new_stage_ids_and_skipped_status_validate() -> None:
    for stage_id in ("approval", "attribution", "footage", "assembly"):
        stage = StageSummary(id=stage_id, label=f"{stage_id} stage", status="queued")
        assert stage.id == stage_id

    skipped = StageSummary(
        id="attribution",
        label="Find the original",
        status="skipped",
        skip_reason="attribution_off",
        started_at="2026-10-25T08:00:00Z",
        finished_at="2026-10-25T08:00:00Z",
    )
    assert skipped.status == "skipped"
    assert skipped.skip_reason == "attribution_off"


def test_the_old_stage_ids_still_validate() -> None:
    for stage_id in ("validation", "source", "assets", "narration", "render", "review", "delivery"):
        assert StageSummary(id=stage_id, label=stage_id, status="running").id == stage_id

    with pytest.raises(ValidationError):
        StageSummary(id="unknown_stage", label="Unknown", status="running")


@pytest.mark.parametrize(
    "reason",
    [
        "attribution_off",
        "footage_off",
        "assembly_off",
        "approval_rejected",
        "not_in_this_version",
        "run_failed",
        "run_cancelled",
    ],
)
def test_skip_reason_accepts_exactly_the_planned_codes(reason: str) -> None:
    stage = StageSummary(
        id="footage", label="Collect footage", status="skipped", skip_reason=reason
    )
    assert stage.skip_reason == reason

    with pytest.raises(ValidationError):
        StageSummary(id="footage", label="Collect footage", status="skipped", skip_reason="because")


def test_an_old_stored_summary_without_the_new_fields_validates() -> None:
    stage = StageSummary.model_validate(json.loads(OLD_STORED_SUMMARY)["stages"][0])
    assert stage.started_at is None
    assert stage.finished_at is None
    assert stage.skip_reason is None


def test_bad_stage_timestamps_are_refused() -> None:
    for bad in ("2026-08-28 08:00:00", "not-a-timestamp", "2026-08-28T08:00:00"):
        with pytest.raises(ValidationError):
            StageSummary(id="source", label="Fetch the source", status="running", started_at=bad)
        with pytest.raises(ValidationError):
            StageSummary(id="source", label="Fetch the source", status="completed", finished_at=bad)

    from datetime import datetime

    naive = datetime(2026, 8, 28, 8, 0, 0)
    with pytest.raises(ValidationError):
        StageSummary(id="source", label="Fetch the source", status="running", started_at=naive)


def test_stage_timestamps_accept_rfc3339_strings_and_datetimes() -> None:
    stage = StageSummary(
        id="source",
        label="Fetch the source",
        status="completed",
        started_at="2026-10-25T08:00:00Z",
        finished_at="2026-10-25T08:02:31+00:00",
    )
    assert stage.started_at is not None and stage.started_at.utcoffset().total_seconds() == 0
    assert stage.finished_at is not None and stage.finished_at > stage.started_at
