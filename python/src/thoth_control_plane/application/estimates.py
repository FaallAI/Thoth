"""The run's remaining-time estimate, pure math over stored summaries (spec G4, D1).

No I/O here: the service supplies the run's summary, the actor's succeeded histories for
the same platform, and `now`; this module turns them into whole seconds or None.
"""

from __future__ import annotations

from datetime import datetime
from statistics import median

from thoth_control_plane.domain import WorkflowStatus, WorkflowSummary

#: Below this many succeeded histories there is no estimate; the UI says "a few minutes".
MIN_HISTORIES = 5
#: Spec defaults when a planned stage has no measured median (spec G4).
STAGE_DEFAULT_SECONDS: dict[str, float] = {
    "source": 120.0,
    "attribution": 60.0,
    "footage": 240.0,
    "assembly": 60.0,
}
#: A person is the wait, not the machine: this stage never counts (D1).
NEVER_COUNTS = "approval"


def _medians(histories: list[WorkflowSummary]) -> dict[str, float]:
    """Median duration in seconds per stage id, over completed stages with both timestamps.
    Pre-phase-1 summaries carry no stage timestamps, so they simply contribute nothing."""
    durations: dict[str, list[float]] = {}
    for history in histories:
        for stage in history.stages:
            if stage.status != "completed" or stage.started_at is None or stage.finished_at is None:
                continue
            durations.setdefault(stage.id, []).append(
                (stage.finished_at - stage.started_at).total_seconds()
            )
    return {stage_id: median(values) for stage_id, values in durations.items()}


def estimate_seconds_remaining(
    summary: WorkflowSummary, histories: list[WorkflowSummary], now: datetime
) -> int | None:
    """The run's remaining whole seconds, or None when no estimate applies (D1).

    None below `MIN_HISTORIES` succeeded runs with stage timings, and for any run that is
    not running or queued; `awaiting_approval` gets None too, because a person is the
    wait. The approval stage never counts. A non-approval stage left `waiting` still has
    all its work ahead, so it counts like `queued`.
    """
    if summary.status not in (WorkflowStatus.RUNNING, WorkflowStatus.QUEUED):
        return None
    # Only runs that recorded stage timings count: runs from before phase 1 carry none,
    # and counting them would show a number built from defaults (DESIGN 7.3).
    timed = [history for history in histories if _medians([history])]
    if len(timed) < MIN_HISTORIES:
        return None
    medians = _medians(timed)
    remaining = 0.0
    for stage in summary.stages:
        if stage.id == NEVER_COUNTS:
            continue
        expected = medians.get(stage.id, STAGE_DEFAULT_SECONDS.get(stage.id, 0.0))
        if stage.status in ("queued", "waiting"):
            remaining += expected
        elif stage.status == "running":
            elapsed = (
                max((now - stage.started_at).total_seconds(), 0.0)
                if stage.started_at is not None
                else 0.0
            )
            wait_remaining = 0.0
            step = stage.current_step
            if step is not None and step.kind == "wait" and step.wait_until is not None:
                wait_remaining = max((step.wait_until - now).total_seconds(), 0.0)
            remaining += max(expected - elapsed, wait_remaining, 0.0)
        # completed, skipped, failed and cancelled stages have nothing left.
    return round(remaining)
