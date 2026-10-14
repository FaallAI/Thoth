from __future__ import annotations

from pathlib import Path

from tests.assembly.support import report as support_report
from thoth_control_plane.activities.footage import (
    FootageActivityInput,
    build_footage_activity,
)
from thoth_control_plane.config import Settings
from thoth_control_plane.footage.models import FootageResult


class Builder:
    def __init__(self) -> None:
        self.inputs: list[object] = []

    async def build(self, inputs: object) -> FootageResult:
        self.inputs.append(inputs)
        return FootageResult(status="ok", admitted=2, rejected={"story": 3})


def _settings(tmp_path: Path, **changes: object) -> Settings:
    return Settings(  # type: ignore[arg-type]
        THOTH_CONTROL_PLANE_API_KEY="k", THOTH_CONTROL_PLANE_ARTIFACT_ROOT=tmp_path, **changes
    )


async def test_disabled_footage_reports_disabled(tmp_path: Path) -> None:
    activity = build_footage_activity(_settings(tmp_path))
    result = await activity(FootageActivityInput(workflow_id="wf_a"))
    assert result.footage_status == "disabled" and result.footage_count == 0


async def test_a_missing_report_is_unavailable(tmp_path: Path) -> None:
    builder = Builder()
    activity = build_footage_activity(_settings(tmp_path), builder=builder)  # type: ignore[arg-type]
    result = await activity(FootageActivityInput(workflow_id="wf_a"))
    assert result.footage_status == "unavailable" and builder.inputs == []


async def test_the_builder_runs_on_the_stage3_report(tmp_path: Path) -> None:
    report = support_report(workflow_id="wf_a")
    folder = tmp_path / "reports" / "wf_a"
    folder.mkdir(parents=True)
    (folder / "source-report.json").write_text(report.model_dump_json(), encoding="utf-8")
    builder = Builder()
    activity = build_footage_activity(_settings(tmp_path), builder=builder)  # type: ignore[arg-type]
    result = await activity(FootageActivityInput(workflow_id="wf_a"))
    assert result.footage_status == "ok" and result.footage_count == 2
    assert result.events[-1].payload["stage"] == "footage"
    assert result.events[-1].payload["footage_count"] == 2
