"""The attribute_source activity: read the repost report, persist the attribution."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from thoth_control_plane.acquisition.models import AcquisitionResult, SourceReport
from thoth_control_plane.activities.source_attribution import (
    RunnerAcquirer,
    SourceAttributionActivityInput,
    _run,
    build_production_ports,
)
from thoth_control_plane.attribution.models import AttributedPost, SourceAttribution
from thoth_control_plane.attribution.ports import AcquiredCandidate
from thoth_control_plane.attribution.service import AttributionOutcome
from thoth_control_plane.config import Settings
from thoth_control_plane.domain.models import SourceProgressEvent

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "tiktok" / "source_report_v3.json"
WORKFLOW = "wf_attr"
ORIGINAL = "https://www.tiktok.com/@vincentius.christ76/video/7677137235434687752"


def _report(workflow_id: str = WORKFLOW) -> SourceReport:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["workflow_id"] = workflow_id
    data["media"][0]["location"] = f"reports/{workflow_id}/media/tiktok-1234567890.mp4"
    return SourceReport.model_validate_json(json.dumps(data))


def _persist(root: Path, report: SourceReport, *, with_video: bool = True) -> None:
    folder = root / "reports" / WORKFLOW
    folder.mkdir(parents=True)
    (folder / "source-report.json").write_text(report.model_dump_json(), encoding="utf-8")
    if with_video:
        (root / report.media[0].location).parent.mkdir(parents=True, exist_ok=True)
        (root / report.media[0].location).write_bytes(b"\x00" * 2000)


class FakeAttributor:
    def __init__(self, outcome: AttributionOutcome | None = None, error: Exception | None = None):
        self.outcome = outcome
        self.error = error
        self.calls: list[tuple[str, SourceReport, Path | None]] = []

    async def identify(self, workflow_id: str, report: SourceReport, video: Path | None) -> Any:
        self.calls.append((workflow_id, report, video))
        if self.error is not None:
            raise self.error
        return self.outcome


def _replaced(original: SourceReport) -> AttributionOutcome:
    attribution = SourceAttribution(
        workflow_id=WORKFLOW,
        input=AttributedPost(
            platform="tiktok",
            canonical_url="https://www.tiktok.com/@creator/video/1234567890",
            owner_handle="creator",
        ),
        verdict="replaced",
        source=AttributedPost(
            platform="tiktok", canonical_url=ORIGINAL, owner_handle="vincentius.christ76"
        ),
        confidence="high",
    )
    return AttributionOutcome(attribution, AcquiredCandidate(f"{WORKFLOW}-c1", original, None))


@pytest.mark.asyncio
async def test_a_replaced_verdict_persists_both_artifacts(tmp_path: Path) -> None:
    report = _report()
    _persist(tmp_path, report)
    attributor = FakeAttributor(_replaced(_report(f"{WORKFLOW}-c1")))

    result = await _run(SourceAttributionActivityInput(workflow_id=WORKFLOW), tmp_path, attributor)

    assert result.verdict == "replaced"
    assert attributor.calls[0][2] == (tmp_path / report.media[0].location).resolve()
    assert result.attribution is not None and result.original_report is not None
    assert result.attribution.kind == "source_attribution"
    assert result.attribution.location == f"reports/{WORKFLOW}/source-attribution.json"
    written = (tmp_path / result.attribution.location).read_bytes()
    assert result.attribution.checksum == f"sha256:{sha256(written).hexdigest()}"
    assert SourceAttribution.model_validate_json(written).verdict == "replaced"
    assert result.original_report.kind == "original_source_report"
    assert result.original_report.location == f"reports/{WORKFLOW}-c1/source-report.json"
    assert (tmp_path / result.original_report.location).is_file()
    assert [event.payload for event in result.events] == [
        {
            "stage": "attribution",
            "status": "succeeded",
            "elapsed_ms": result.events[0].payload["elapsed_ms"],
            "verdict": "replaced",
        }
    ]


@pytest.mark.asyncio
async def test_a_missing_video_file_is_passed_as_none(tmp_path: Path) -> None:
    _persist(tmp_path, _report(), with_video=False)
    attributor = FakeAttributor(_replaced(_report(f"{WORKFLOW}-c1")))

    await _run(SourceAttributionActivityInput(workflow_id=WORKFLOW), tmp_path, attributor)

    assert attributor.calls[0][2] is None


@pytest.mark.asyncio
async def test_an_unreadable_report_is_unresolved_without_artifacts(tmp_path: Path) -> None:
    folder = tmp_path / "reports" / WORKFLOW
    folder.mkdir(parents=True)
    (folder / "source-report.json").write_text('{"legacy": true}', encoding="utf-8")
    attributor = FakeAttributor()

    result = await _run(SourceAttributionActivityInput(workflow_id=WORKFLOW), tmp_path, attributor)

    assert (result.verdict, result.attribution, result.original_report) == (
        "unresolved",
        None,
        None,
    )
    assert result.events[0].payload["status"] == "failed"
    assert attributor.calls == []


@pytest.mark.asyncio
async def test_a_required_tool_failure_is_a_typed_failure(tmp_path: Path) -> None:
    from thoth_control_plane.attribution.ports import AttributionError

    _persist(tmp_path, _report())

    result = await _run(
        SourceAttributionActivityInput(workflow_id=WORKFLOW),
        tmp_path,
        FakeAttributor(error=AttributionError("decision_unavailable")),
    )

    assert (result.verdict, result.failure) == ("unresolved", "decision_unavailable")
    assert result.attribution is None and result.original_report is None
    assert result.events[0].payload["reason"] == "decision_unavailable"
    assert result.events[0].kind == "stage.failed"
    assert not (tmp_path / "reports" / WORKFLOW / "source-attribution.json").exists()


@pytest.mark.asyncio
async def test_an_attributor_error_is_unresolved(tmp_path: Path) -> None:
    _persist(tmp_path, _report())

    result = await _run(
        SourceAttributionActivityInput(workflow_id=WORKFLOW),
        tmp_path,
        FakeAttributor(error=RuntimeError("secret detail must not leak")),
    )

    assert result.verdict == "unresolved"
    assert "secret detail" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_the_runner_acquirer_returns_the_candidate_and_its_video(tmp_path: Path) -> None:
    candidate = f"{WORKFLOW}-c1"
    report = _report(candidate)
    (tmp_path / report.media[0].location).parent.mkdir(parents=True)
    (tmp_path / report.media[0].location).write_bytes(b"\x00" * 2000)

    async def runner(workflow_id: str, url: str, root: Path) -> AcquisitionResult:
        assert (workflow_id, url, root) == (candidate, ORIGINAL, tmp_path)
        return AcquisitionResult(report=report)

    acquired = await RunnerAcquirer(runner, tmp_path).acquire(candidate, ORIGINAL)

    assert acquired is not None and acquired.candidate_id == candidate
    assert acquired.video == (tmp_path / report.media[0].location).resolve()


@pytest.mark.asyncio
async def test_discard_removes_only_a_candidate_directory_inside_the_root(tmp_path: Path) -> None:
    async def runner(*_: Any) -> AcquisitionResult:
        raise AssertionError("not called")

    keep = tmp_path / "reports" / WORKFLOW
    gone = tmp_path / "reports" / f"{WORKFLOW}-c2"
    for folder in (keep, gone):
        folder.mkdir(parents=True)
        (folder / "x").write_bytes(b"1")
    acquirer = RunnerAcquirer(runner, tmp_path)

    await acquirer.discard(f"{WORKFLOW}-c2")
    await acquirer.discard("../outside")
    await acquirer.discard("")

    assert keep.is_dir() and not gone.exists()


def test_production_ports_follow_the_configured_keys(tmp_path: Path) -> None:
    common: dict[str, Any] = {
        "THOTH_CONTROL_PLANE_API_KEY": "k",
        "THOTH_CONTROL_PLANE_ARTIFACT_ROOT": tmp_path,
    }
    without = build_production_ports(Settings(**common, THOTH_OPENROUTER_API_KEY=None), tmp_path)
    with_keys = build_production_ports(
        Settings(
            **common,
            THOTH_OPENROUTER_API_KEY="or-synthetic-key",
        ),
        tmp_path,
    )

    assert (without.vision, without.decisions) == (None, None)
    assert with_keys.vision is not None and with_keys.decisions is not None


def test_provider_keys_never_reach_an_adapter_repr_or_the_ports(tmp_path: Path) -> None:
    # Spec section 8: keys live only inside the two adapters; nothing the activity persists or
    # returns is built from an adapter, so a key that is absent from their repr cannot leak.
    ports = build_production_ports(
        Settings(
            THOTH_CONTROL_PLANE_API_KEY="k",
            THOTH_CONTROL_PLANE_ARTIFACT_ROOT=tmp_path,
            THOTH_OPENROUTER_API_KEY="or-canary-0123456789",
        ),
        tmp_path,
    )

    rendered = repr(ports)
    assert "or-canary" not in rendered


def test_the_verdict_is_a_closed_event_payload_value() -> None:
    SourceProgressEvent(
        kind="stage.completed",
        payload={"stage": "attribution", "status": "succeeded", "verdict": "original"},
    )
    with pytest.raises(ValueError):
        SourceProgressEvent(
            kind="stage.completed", payload={"stage": "attribution", "verdict": "@someone"}
        )


def test_production_discovery_leases_from_the_account_store_when_configured(
    tmp_path: Path,
) -> None:
    from cryptography.fernet import Fernet

    from thoth_control_plane.attribution.adapters.discovery import StoreLeases

    common: dict[str, Any] = {
        "THOTH_CONTROL_PLANE_API_KEY": "k",
        "THOTH_CONTROL_PLANE_ARTIFACT_ROOT": tmp_path,
    }
    anonymous = build_production_ports(Settings(**common), tmp_path)
    signed_in = build_production_ports(
        Settings(
            **common,
            THOTH_ACCOUNT_VAULT_KEY=Fernet.generate_key().decode(),
            THOTH_EDITOR_DATABASE_URL="postgresql://u:p@127.0.0.1:1/editor",
        ),
        tmp_path,
    )

    assert anonymous.discoverer._leases is None  # type: ignore[attr-defined]
    assert isinstance(signed_in.discoverer._leases, StoreLeases)  # type: ignore[attr-defined]
