"""WorkflowStep domain contract (run-progress spec 2026-10-25, phase 2, D1)."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from thoth_control_plane.domain.models import StageSummary, WorkflowStep, WorkflowStepPage

AT = "2026-10-25T10:00:00Z"


def step(**overrides: object) -> dict:
    values: dict = {
        "seq": 3,
        "stage": "source",
        "attempt": 2,
        "at": AT,
        "kind": "progress",
        "code": "source.download_media",
        "n": 4,
        "total": 12,
    }
    values.update(overrides)
    return values


def stage_summary(**overrides: object) -> dict:
    values: dict = {
        "id": "source",
        "label": "Investigate original source",
        "status": "running",
    }
    values.update(overrides)
    return values


def test_a_valid_step_validates_from_strings_and_datetimes() -> None:
    from_strings = WorkflowStep.model_validate(step())
    from_objects = WorkflowStep.model_validate(
        step(at=datetime(2026, 10, 25, 10, 0, tzinfo=UTC), wait_until=AT)
    )
    assert (from_strings.seq, from_strings.n, from_strings.total) == (3, 4, 12)
    assert from_strings.params is None
    assert from_objects.wait_until == datetime(2026, 10, 25, 10, 0, tzinfo=UTC)


def test_every_stage_and_kind_is_accepted() -> None:
    for stage, code in (
        ("source", "source.read_link"),
        ("attribution", "attribution.verdict"),
        ("footage", "footage.search_platforms"),
        ("assembly", "assembly.save_content_set"),
    ):
        assert WorkflowStep.model_validate(step(stage=stage, code=code, kind="info")).stage == stage
    for kind in ("info", "progress", "wait", "done", "warning", "error"):
        assert WorkflowStep.model_validate(step(kind=kind)).kind == kind


@pytest.mark.parametrize(
    "overrides",
    [
        {"code": "source.ReadLink"},  # uppercase segment
        {"code": "read_link"},  # no stage prefix
        {"code": "narration.read_link"},  # a stage outside the four
        {"stage": "validation"},
        {"stage": "attribution", "code": "attribution.verdict", "kind": "bogus"},
        {"seq": 0},
        {"attempt": 0},
        {"n": -1},
        {"total": -2},
        {"params": {"verdict": {"deep": True}}},
        {"params": ["verdict"]},
    ],
)
def test_a_bad_step_is_refused(overrides: dict) -> None:
    with pytest.raises(ValidationError):
        WorkflowStep.model_validate(step(**overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"at": "2026-10-25 10:00:00"},  # a space, not RFC 3339
        {"at": "2026-10-25T10:00:00"},  # no offset
        {"at": "not-a-timestamp"},
        {"at": datetime(2026, 10, 25, 10, 0)},  # naive datetime
        {"wait_until": "2026-10-25T10:00:00"},  # no offset
    ],
)
def test_a_bad_timestamp_is_refused(overrides: dict) -> None:
    with pytest.raises(ValidationError, match="timestamp must be RFC 3339"):
        WorkflowStep.model_validate(step(**overrides))


def test_a_step_page_holds_its_steps_in_order() -> None:
    first = WorkflowStep.model_validate(
        step(code="source.read_link", kind="info", n=None, total=None)
    )
    second = WorkflowStep.model_validate(step(seq=4, code="source.fetch_post"))
    page = WorkflowStepPage.model_validate({"steps": [first, second]})
    assert [s.code for s in page.steps] == ["source.read_link", "source.fetch_post"]
    assert WorkflowStepPage.model_validate({"steps": []}).steps == []


def test_an_old_stage_summary_without_current_step_still_validates() -> None:
    legacy = StageSummary.model_validate(stage_summary())
    assert legacy.current_step is None
    filled = StageSummary.model_validate(
        stage_summary(current_step=step(), status="waiting", skip_reason=None)
    )
    assert filled.current_step is not None and filled.current_step.code == "source.download_media"
