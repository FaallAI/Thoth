"""The pure stage-plan state behind `WorkflowSummary.stages` (spec 2026-10-25, G1).

The plan is built once from the intent and the chain flags (D1) and then driven by
the workflow through explicit transitions (D3). It is plain Python plus the domain
models: no Temporal import, so it stays unit-testable and safe inside the workflow
sandbox, and no transition it records issues a Temporal command.
"""

from __future__ import annotations

from datetime import datetime

from thoth_control_plane.domain.models import StageSummary

# D1 stage labels, from the design table (docs/DESIGN.md §7.1).
_LABELS: dict[str, str] = {
    "source": "Fetch the source",
    "approval": "Your review",
    "attribution": "Find the original",
    "footage": "Collect footage",
    "assembly": "Build the content set",
}


class _Stage:
    """Mutable per-stage state; `StagePlan.snapshot()` turns it into `StageSummary`."""

    __slots__ = ("finished_at", "skip_reason", "stage_id", "started_at", "status")

    def __init__(self, stage_id: str) -> None:
        self.stage_id = stage_id
        self.status: str = "queued"
        self.started_at: datetime | None = None
        self.finished_at: datetime | None = None
        self.skip_reason: str | None = None


class StagePlan:
    """Ordered stage state for one workflow run.

    Transitions are idempotent and never touch a stage that was already decided,
    except `fail`, which overrides a recorded completion: `_attribute` and
    `_assemble` record their STAGE_COMPLETED event before the workflow decides the
    run failed, and the plan must report the failure, not the completion.
    """

    def __init__(self, stages: list[_Stage]) -> None:
        self._stages = stages

    def start(self, stage_id: str, at: datetime) -> None:
        stage = self._stage(stage_id)
        if stage.status != "queued":
            return
        stage.status = "running"
        stage.started_at = at

    def wait(self, stage_id: str, at: datetime) -> None:
        stage = self._stage(stage_id)
        if stage.status not in {"queued", "running"}:
            return
        stage.status = "waiting"
        if stage.started_at is None:
            stage.started_at = at

    def complete(self, stage_id: str, at: datetime) -> None:
        stage = self._stage(stage_id)
        if stage.status in {"completed", "skipped", "failed", "cancelled"}:
            return
        stage.status = "completed"
        if stage.started_at is None:
            stage.started_at = at
        stage.finished_at = at

    def fail(self, stage_id: str, at: datetime) -> None:
        stage = self._stage(stage_id)
        if stage.status in {"failed", "skipped"}:
            return
        stage.status = "failed"
        if stage.started_at is None:
            stage.started_at = at
        stage.finished_at = at
        stage.skip_reason = None

    def cancel_open(self, at: datetime) -> None:
        for stage in self._stages:
            if stage.status in {"running", "waiting"}:
                stage.status = "cancelled"
                stage.finished_at = at
            elif stage.status == "queued":
                stage.status = "skipped"
                stage.skip_reason = "run_cancelled"

    def skip_queued(self, reason: str) -> None:
        for stage in self._stages:
            if stage.status == "queued":
                stage.status = "skipped"
                stage.skip_reason = reason

    def snapshot(self) -> list[StageSummary]:
        return [
            StageSummary(
                id=stage.stage_id,
                label=_LABELS[stage.stage_id],
                status=stage.status,  # type: ignore[arg-type]
                # D5: only `source` ever reports progress, and only once it completed;
                # steps arrive for the other stages in phase 2.
                progress=(
                    1.0 if stage.stage_id == "source" and stage.status == "completed" else None
                ),
                started_at=stage.started_at,
                finished_at=stage.finished_at,
                skip_reason=stage.skip_reason,  # type: ignore[arg-type]
            )
            for stage in self._stages
        ]

    def _stage(self, stage_id: str) -> _Stage:
        for stage in self._stages:
            if stage.stage_id == stage_id:
                return stage
        raise KeyError(stage_id)


def build_plan(
    intent: str,
    *,
    attribute_source: bool,
    assemble_content: bool,
    build_footage: bool,
) -> StagePlan:
    """Build the whole plan from the intent and the chain flags (D1).

    `source` always runs. `approval` exists only for `produce_video`. The chain
    stages are in the plan even when their flag is off: they appear as `skipped`
    with their off code from the very first snapshot, so the run shows its whole
    plan from the start.
    """
    if intent not in {"identify_original", "produce_video"}:
        raise ValueError(f"unknown intent: {intent}")
    off_codes = {
        "attribution": "attribution_off",
        "footage": "footage_off",
        "assembly": "assembly_off",
    }
    enabled = {
        "attribution": attribute_source,
        "footage": assemble_content and build_footage,
        "assembly": assemble_content,
    }
    ids = ["source"]
    if intent == "produce_video":
        ids.append("approval")
    ids.extend(off_codes)
    stages: list[_Stage] = []
    for stage_id in ids:
        stage = _Stage(stage_id)
        if stage_id in off_codes and not enabled[stage_id]:
            stage.status = "skipped"
            stage.skip_reason = off_codes[stage_id]
        stages.append(stage)
    return StagePlan(stages)
