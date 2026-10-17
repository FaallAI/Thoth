"""The `attribute_source` activity: attribute a persisted repost report, persist the result.

It reads `reports/<workflow_id>/source-report.json` (only a Stage 3 report, schema v3, is
accepted), runs the attributor, and writes the attribution and, when found, the original's
report. A required tool, model, or provider that cannot work is a typed failure carrying its
code, and the workflow fails (operator, 2026-10-13); any other failure is verdict `unresolved`
with a failed event, and the repost acquisition stands. Only IDs, the verdict, codes, and
elapsed milliseconds reach Temporal history.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import re
import shutil
import time
from collections.abc import Awaitable, Callable
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol

from pydantic import Field
from temporalio import activity

from thoth_control_plane.acquisition.models import SourceReport
from thoth_control_plane.activities.media_scratch import (
    MediaScratch,
    heartbeating,
    report_media_locations,
)
from thoth_control_plane.activities.source_investigation import (
    AcquisitionRunner,
    _account_profiles,
    _account_store,
    build_production_acquisition_runner,
)
from thoth_control_plane.attribution.adapters.discovery import ProfileDiscoverer, StoreLeases
from thoth_control_plane.attribution.adapters.frames import (
    FfmpegFrameSource,
    FfmpegSceneDetector,
)
from thoth_control_plane.attribution.adapters.jev import JevDecisionModel
from thoth_control_plane.attribution.adapters.motion import PillowMotion
from thoth_control_plane.attribution.adapters.ocr import RapidOcrReader
from thoth_control_plane.attribution.adapters.speech import SherpaDiarizer, WhisperTranscriber
from thoth_control_plane.attribution.adapters.vision import AgnoVisionReader
from thoth_control_plane.attribution.adapters.visual import OrbMatcher
from thoth_control_plane.attribution.candidates import load_curated
from thoth_control_plane.attribution.models import ReasonCode
from thoth_control_plane.attribution.ports import AcquiredCandidate, AttributionError
from thoth_control_plane.attribution.service import (
    AttributionOutcome,
    AttributionPorts,
    SourceAttributor,
)
from thoth_control_plane.config import Settings, SettingsValidationError
from thoth_control_plane.domain import ArtifactRef
from thoth_control_plane.domain.models import (
    OPAQUE_ID_PATTERN,
    OpaqueId,
    SourceProgressEvent,
    StrictModel,
)
from thoth_control_plane.infrastructure.media_store import (
    LocalMediaStore,
    MediaStore,
    build_media_store,
)
from thoth_control_plane.infrastructure.report_store import Reports, connect_reports, read_report

logger = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 30.0
ATTRIBUTION_FILE = "source-attribution.json"
REPORT_FILE = "source-report.json"
Verdict = Literal["original", "replaced", "unresolved"]
#: The running attribution's scratch root: candidates are acquired below it (spec 2026-10-17).
ACQUISITION_ROOT: contextvars.ContextVar[Path] = contextvars.ContextVar("attribution_root")


class SourceAttributionActivityInput(StrictModel):
    workflow_id: OpaqueId


class SourceAttributionActivityResult(StrictModel):
    verdict: Verdict
    attribution: ArtifactRef | None = None
    original_report: ArtifactRef | None = None
    failure: ReasonCode | None = None
    events: list[SourceProgressEvent] = Field(default_factory=list)


class Attributor(Protocol):
    async def identify(
        self, workflow_id: str, report: SourceReport, video: Path | None
    ) -> AttributionOutcome: ...


def _video(report: SourceReport, artifact_root: Path) -> Path | None:
    root = artifact_root.resolve()
    for media in report.media:
        if media.kind == "video":
            path = (artifact_root / media.location).resolve()
            return path if path.is_relative_to(root) and path.is_file() else None
    return None


class RunnerAcquirer:
    """Acquire candidates through the production runner, each under its own report key, below
    the running attribution's scratch root (or the given root outside an attribution)."""

    def __init__(self, runner: AcquisitionRunner, artifact_root: Path | None = None) -> None:
        self._runner = runner
        self._fallback = artifact_root

    @property
    def _root(self) -> Path:
        root = ACQUISITION_ROOT.get(self._fallback)
        if root is None:
            raise RuntimeError("no acquisition root")
        return root

    async def acquire(self, candidate_id: str, url: str) -> AcquiredCandidate | None:
        root = self._root
        result = await self._runner(candidate_id, url, root)
        if result.report is None:
            return None
        return AcquiredCandidate(candidate_id, result.report, _video(result.report, root))

    async def discard(self, candidate_id: str) -> None:
        if not re.fullmatch(OPAQUE_ID_PATTERN, candidate_id):
            return
        reports = (self._root / "reports").resolve()
        target = (reports / candidate_id).resolve()
        if target.parent == reports:
            await asyncio.to_thread(shutil.rmtree, target, True)


def build_production_ports(settings: Settings, artifact_root: Path) -> AttributionPorts:
    openrouter = settings.openrouter_api_key
    if openrouter is None:
        # Operator, 2026-10-13: vision and Jev are required; there is no rules-only path.
        raise SettingsValidationError("openrouter_key_missing")
    store = _account_store(settings)
    return AttributionPorts(
        frames=FfmpegFrameSource(settings.THOTH_FFMPEG),
        matcher=OrbMatcher(),
        text=RapidOcrReader(),
        discoverer=ProfileDiscoverer(
            leases=StoreLeases(store, _account_profiles(settings)) if store is not None else None
        ),
        acquirer=RunnerAcquirer(build_production_acquisition_runner(settings), artifact_root),
        vision=AgnoVisionReader(openrouter, settings.THOTH_SOURCE_VISION_MODEL),
        decisions=JevDecisionModel(openrouter),
        scenes=FfmpegSceneDetector(settings.THOTH_FFMPEG),
        transcriber=WhisperTranscriber(settings.THOTH_WHISPER_MODEL_DIR),
        diarizer=SherpaDiarizer(settings.THOTH_DIARIZATION_MODEL_DIR),
        motion=PillowMotion(),
    )


def _artifact(kind: str, label: str, location: PurePosixPath, content: bytes) -> ArtifactRef:
    digest = sha256(content).hexdigest()
    return ArtifactRef(
        artifact_id=f"art_{kind}_{digest[:20]}",
        kind=kind,
        label=label,
        media_type="application/json",
        location=location.as_posix(),
        checksum=f"sha256:{digest}",
        size_bytes=len(content),
    )


def _event(
    verdict: Verdict,
    elapsed_ms: int,
    status: Literal["succeeded", "failed"],
    reason: str | None = None,
) -> SourceProgressEvent:
    payload: dict[str, str | int | float | bool | None] = {
        "stage": "attribution",
        "status": status,
        "elapsed_ms": elapsed_ms,
        "verdict": verdict,
    }
    if reason is not None:
        payload["reason"] = reason
    return SourceProgressEvent(
        kind="stage.completed" if status == "succeeded" else "stage.failed", payload=payload
    )


async def _heartbeat() -> None:
    while True:
        if activity.in_activity():
            activity.heartbeat()
        await asyncio.sleep(HEARTBEAT_SECONDS)


async def _run(
    input_: SourceAttributionActivityInput,
    artifact_root: Path,
    attributor: Attributor,
    reports: Reports,
    *,
    media: MediaStore | None = None,
    scratch_dir: Path | None = None,
) -> SourceAttributionActivityResult:
    started = time.monotonic()

    def failed() -> SourceAttributionActivityResult:
        elapsed = int((time.monotonic() - started) * 1000)
        return SourceAttributionActivityResult(
            verdict="unresolved", events=[_event("unresolved", elapsed, "failed")]
        )

    folder = PurePosixPath("reports") / input_.workflow_id
    report = await read_report(reports, (folder / REPORT_FILE).as_posix(), SourceReport)
    if report is None:
        logger.warning("source attribution skipped; no stage 3 report for this workflow")
        return failed()

    store = media or LocalMediaStore(artifact_root)
    async with heartbeating(_heartbeat), MediaScratch(store, scratch_dir) as scratch:
        # The repost's first video: what `_video` hands the attributor.
        await scratch.pull([str(m.location) for m in report.media if m.kind == "video"][:1])
        token = ACQUISITION_ROOT.set(scratch.root)
        try:
            outcome = await attributor.identify(
                input_.workflow_id, report, _video(report, scratch.root)
            )
        except asyncio.CancelledError:
            raise
        except AttributionError as error:
            logger.warning("source attribution stopped: %s", error.code)
            elapsed = int((time.monotonic() - started) * 1000)
            return SourceAttributionActivityResult(
                verdict="unresolved",
                failure=error.code,
                events=[_event("unresolved", elapsed, "failed", error.code)],
            )
        except Exception:
            logger.warning("source attribution failed; the repost report stands")
            return failed()
        finally:
            ACQUISITION_ROOT.reset(token)

        content = outcome.attribution.model_dump_json(indent=2).encode("utf-8")
        location = folder / ATTRIBUTION_FILE
        await asyncio.to_thread(reports.put, location.as_posix(), "source_attribution", content)
        attribution = _artifact("source_attribution", "Source attribution", location, content)
        original = None
        if outcome.original is not None:
            # The original's media goes up before its report row, as acquisition does.
            await scratch.push(report_media_locations(outcome.original.report))
            original_location = (
                PurePosixPath("reports") / outcome.original.candidate_id / REPORT_FILE
            )
            original_content = outcome.original.report.model_dump_json(indent=2).encode("utf-8")
            await asyncio.to_thread(
                reports.put,
                original_location.as_posix(),
                "original_source_report",
                original_content,
            )
            original = _artifact(
                "original_source_report",
                "Original source report",
                original_location,
                original_content,
            )

        verdict = outcome.attribution.verdict
        elapsed = int((time.monotonic() - started) * 1000)
        return SourceAttributionActivityResult(
            verdict=verdict,
            attribution=attribution,
            original_report=original,
            events=[_event(verdict, elapsed, "succeeded")],
        )


@activity.defn(name="attribute_source")
async def attribute_source(
    input_: SourceAttributionActivityInput,
) -> SourceAttributionActivityResult:
    """Activity-name reference for workflow definitions and direct local use."""
    configured = build_source_attribution_activity(Settings())  # type: ignore[call-arg]
    return await configured(input_)


class _OnFirstUse:
    """The production attributor, built when an attribution first runs.

    The worker registers this activity even with attribution switched off (the kill switch),
    so a missing key must not stop it from starting; it fails the attribution instead.
    """

    def __init__(self, settings: Settings, artifact_root: Path | None = None) -> None:
        self._settings = settings
        self._root = artifact_root
        self._inner: SourceAttributor | None = None

    async def identify(
        self, workflow_id: str, report: SourceReport, video: Path | None
    ) -> AttributionOutcome:
        if self._inner is None:
            try:
                ports = build_production_ports(self._settings, self._root)
            except SettingsValidationError as error:
                raise AttributionError(str(error)) from None
            self._inner = SourceAttributor(ports, curated=load_curated())
        return await self._inner.identify(workflow_id, report, video)


def build_source_attribution_activity(
    settings: Settings,
    *,
    attributor: Attributor | None = None,
    reports: Reports | None = None,
    media: MediaStore | None = None,
) -> Callable[[SourceAttributionActivityInput], Awaitable[SourceAttributionActivityResult]]:
    artifact_root = settings.THOTH_CONTROL_PLANE_ARTIFACT_ROOT.resolve()
    # No fallback root: candidates land only below the running attribution's scratch.
    selected = attributor or _OnFirstUse(settings)
    selected_reports = reports or connect_reports(settings)
    selected_media = media or build_media_store(settings)
    scratch_dir = settings.THOTH_MEDIA_SCRATCH_DIR

    @activity.defn(name="attribute_source")
    async def configured_source_attribution_activity(
        input_: SourceAttributionActivityInput,
    ) -> SourceAttributionActivityResult:
        return await _run(
            input_,
            artifact_root,
            selected,
            selected_reports,
            media=selected_media,
            scratch_dir=scratch_dir,
        )

    return configured_source_attribution_activity
