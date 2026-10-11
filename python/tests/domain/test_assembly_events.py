"""Assembly progress events: counts, an OCR outcome, and a known failure reason only."""

import pytest

from thoth_control_plane.domain.models import SourceProgressEvent


def test_assembly_events_carry_counts_and_a_known_reason() -> None:
    event = SourceProgressEvent(
        kind="stage.completed",
        payload={
            "stage": "assembly",
            "status": "succeeded",
            "elapsed_ms": 9,
            "ocr_outcome": "cover",
            "comment_count": 12,
            "figure_count": 0,
        },
    )
    assert event.payload["ocr_outcome"] == "cover"
    failed = SourceProgressEvent(
        kind="stage.failed",
        payload={"stage": "assembly", "status": "failed", "reason": "incomplete_frame_coverage"},
    )
    assert failed.payload["reason"] == "incomplete_frame_coverage"


@pytest.mark.parametrize(
    "payload",
    [
        {"stage": "assembly", "ocr_outcome": "blurry"},
        {"stage": "assembly", "comment_count": -1},
        {"stage": "assembly", "figure_count": True},
        {"stage": "assembly", "reason": "something_else"},
    ],
)
def test_assembly_event_values_are_checked(payload: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        SourceProgressEvent(kind="stage.completed", payload=payload)
