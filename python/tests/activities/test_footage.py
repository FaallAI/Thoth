from __future__ import annotations

from pathlib import Path

import pytest
from temporalio.exceptions import ApplicationError

from tests.assembly.support import report as support_report
from tests.conftest import DownReports
from thoth_control_plane.activities.footage import (
    FootageActivityInput,
    build_footage_activity,
)
from thoth_control_plane.assembly.ports import AssemblyError
from thoth_control_plane.config import Settings
from thoth_control_plane.footage.models import FootageResult
from thoth_control_plane.infrastructure.report_store import ReportStoreUnavailable


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


async def test_disabled_footage_reports_disabled(tmp_path: Path, report_store) -> None:
    activity = build_footage_activity(_settings(tmp_path), reports=report_store)
    result = await activity(FootageActivityInput(workflow_id="wf_a"))
    assert result.footage_status == "disabled" and result.footage_count == 0


async def test_a_missing_report_is_unavailable(tmp_path: Path, report_store) -> None:
    builder = Builder()
    activity = build_footage_activity(_settings(tmp_path), builder=builder, reports=report_store)  # type: ignore[arg-type]
    result = await activity(FootageActivityInput(workflow_id="wf_a"))
    assert result.footage_status == "unavailable" and builder.inputs == []


async def test_the_builder_runs_on_the_stage3_report(tmp_path: Path, report_store) -> None:
    _with_report(report_store)
    builder = Builder()
    activity = build_footage_activity(_settings(tmp_path), builder=builder, reports=report_store)  # type: ignore[arg-type]
    result = await activity(FootageActivityInput(workflow_id="wf_a"))
    assert result.footage_status == "ok" and result.footage_count == 2
    assert result.events[-1].payload["stage"] == "footage"
    assert result.events[-1].payload["footage_count"] == 2


class Raising:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def build(self, inputs: object) -> FootageResult:
        raise self.error


def _with_report(store) -> None:
    report = support_report(workflow_id="wf_a")
    store.put(
        "reports/wf_a/source-report.json", "source_report", report.model_dump_json().encode("utf-8")
    )


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (RuntimeError("https://x.com/a/status/1 secret caption"), "footage_failed"),
        (AssemblyError("ffmpeg_missing"), "ffmpeg_missing"),
    ],
)
async def test_a_builder_failure_reaches_history_as_a_code_only(
    tmp_path: Path, report_store, error: Exception, code: str
) -> None:
    _with_report(report_store)
    activity = build_footage_activity(
        _settings(tmp_path), builder=Raising(error), reports=report_store
    )  # type: ignore[arg-type]
    with pytest.raises(ApplicationError) as raised:
        await activity(FootageActivityInput(workflow_id="wf_a"))
    assert raised.value.message == code
    assert "secret" not in str(raised.value) and "x.com" not in str(raised.value)


async def test_the_reported_count_is_clamped_to_six(tmp_path: Path, report_store) -> None:
    _with_report(report_store)

    class Many:
        async def build(self, inputs: object) -> FootageResult:
            return FootageResult(status="ok", admitted=9)

    activity = build_footage_activity(_settings(tmp_path), builder=Many(), reports=report_store)  # type: ignore[arg-type]
    result = await activity(FootageActivityInput(workflow_id="wf_a"))
    assert result.footage_count == 6


async def test_footage_raises_when_the_database_is_down(tmp_path: Path) -> None:
    activity = build_footage_activity(
        _settings(tmp_path),
        builder=Builder(),
        reports=DownReports(),  # type: ignore[arg-type]
    )
    with pytest.raises(ReportStoreUnavailable):
        await activity(FootageActivityInput(workflow_id="wf_down"))


@pytest.mark.parametrize("field", ["attribution", "original_report"])
async def test_an_outage_on_an_optional_read_is_not_a_builder_failure(
    tmp_path: Path, report_store, field: str
) -> None:
    _with_report(report_store)
    location = {
        "attribution": "reports/wf_a/source-attribution.json",
        "original_report": "reports/wf_a-c1/source-report.json",
    }[field]

    class FailsOn(DownReports):
        def get(self, loc: str) -> bytes | None:
            if loc == location:
                return super().get(loc)
            return report_store.get(loc)

    activity = build_footage_activity(
        _settings(tmp_path),
        builder=Builder(),
        reports=FailsOn(),  # type: ignore[arg-type]
    )
    with pytest.raises(ReportStoreUnavailable):
        await activity(FootageActivityInput(workflow_id="wf_a", **{field: location}))


async def test_footage_works_on_pulled_media_and_pushes_its_clips(
    tmp_path: Path, report_store
) -> None:
    from thoth_control_plane.infrastructure.media_store import LocalMediaStore

    store_root = tmp_path / "store"
    store_root.mkdir()
    store = LocalMediaStore(store_root)
    _with_report(report_store)
    main = str(support_report(workflow_id="wf_a").media[0].location)
    (tmp_path / "main.mp4").write_bytes(b"main-video")
    store.put_file(main, tmp_path / "main.mp4")
    (tmp_path / "earlier.mp4").write_bytes(b"admitted-before")
    store.put_file("reports/wf_a/footage/earlier.mp4", tmp_path / "earlier.mp4")

    class Building:
        async def build(self, inputs) -> FootageResult:
            root = inputs.artifact_root
            assert (root / main).read_bytes() == b"main-video"
            assert (root / "reports/wf_a/footage/earlier.mp4").read_bytes() == b"admitted-before"
            (root / "reports/wf_a/footage/new.mp4").write_bytes(b"new-clip")
            (root / "reports/wf_a/footage/half.mp4.part").write_bytes(b"x")
            await inputs.publish()  # the service publishes before it marks the run done
            return FootageResult(status="ok", admitted=2)

    activity = build_footage_activity(
        _settings(tmp_path / "unused-root"), builder=Building(), reports=report_store, media=store
    )  # type: ignore[arg-type]
    result = await activity(FootageActivityInput(workflow_id="wf_a"))

    assert result.footage_status == "ok"
    assert store.stat("reports/wf_a/footage/new.mp4").size_bytes == len(b"new-clip")
    assert store.list("reports/wf_a/footage/") == [
        "reports/wf_a/footage/earlier.mp4",
        "reports/wf_a/footage/new.mp4",
    ]


async def test_a_failed_build_pushes_no_clip(tmp_path: Path, report_store) -> None:
    from thoth_control_plane.infrastructure.media_store import LocalMediaStore

    store_root = tmp_path / "store"
    store_root.mkdir()
    store = LocalMediaStore(store_root)
    _with_report(report_store)

    class HalfDone:
        async def build(self, inputs) -> FootageResult:
            clip = inputs.artifact_root / "reports/wf_a/footage/new.mp4"
            clip.parent.mkdir(parents=True, exist_ok=True)
            clip.write_bytes(b"new-clip")
            raise RuntimeError("search failed")

    activity = build_footage_activity(
        _settings(tmp_path / "unused-root"), builder=HalfDone(), reports=report_store, media=store
    )  # type: ignore[arg-type]
    with pytest.raises(ApplicationError):
        await activity(FootageActivityInput(workflow_id="wf_a"))
    assert store.list("reports/wf_a/footage/") == []
