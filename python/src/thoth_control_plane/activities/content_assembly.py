"""The `assemble_content` activity: build the Content Set from the persisted reports.

It reads `reports/<workflow_id>/source-report.json`, the attribution beside it when present,
and the original's report at the location the workflow passes, from the report store, runs the
assembler, and stores `reports/<workflow_id>/content-set.json` there. A required part that
fails returns its reason code; nothing is written. An unreachable store raises, so Temporal
retries. Only IDs, codes, counts, and elapsed milliseconds reach
Temporal history.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Annotated, Protocol

from pydantic import Field, model_validator
from temporalio import activity

from thoth_control_plane.acquisition.models import SourceReport
from thoth_control_plane.activities.media_scratch import (
    MediaScratch,
    heartbeating,
    media_locations,
)
from thoth_control_plane.assembly.models import ContentSet
from thoth_control_plane.assembly.ports import AssemblyError
from thoth_control_plane.assembly.service import AssemblyInputs
from thoth_control_plane.attribution.models import SourceAttribution
from thoth_control_plane.config import Settings
from thoth_control_plane.domain import ArtifactRef
from thoth_control_plane.domain.models import OpaqueId, SourceProgressEvent, StrictModel
from thoth_control_plane.infrastructure.media_store import (
    LocalMediaStore,
    MediaStore,
    build_media_store,
)
from thoth_control_plane.infrastructure.report_store import Reports, connect_reports, read_report

logger = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 30.0
CONTENT_SET_FILE = "content-set.json"
REPORT_FILE = "source-report.json"
ORIGINAL_LOCATION = re.compile(r"^reports/[A-Za-z][A-Za-z0-9_-]{0,127}/source-report\.json$")
ATTRIBUTION_LOCATION = re.compile(
    r"^reports/[A-Za-z][A-Za-z0-9_-]{0,127}/source-attribution\.json$"
)
ReasonCode = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class ContentAssemblyActivityInput(StrictModel):
    workflow_id: OpaqueId
    # What attribute_source reported to the workflow. A file left on disk by a crashed attempt
    # is never read: assembly follows the verdict the workflow received (review, 2026-10-12).
    attribution: str | None = None
    # Where attribute_source wrote the original's report; set only when it found one.
    original_report: str | None = None


class ContentAssemblyActivityResult(StrictModel):
    content_set: ArtifactRef | None = None
    failure: ReasonCode | None = None
    events: list[SourceProgressEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def one_outcome(self) -> ContentAssemblyActivityResult:
        if (self.content_set is None) == (self.failure is None):
            raise ValueError("an assembly result holds a content set or a failure")
        return self


class Assembler(Protocol):
    async def build(self, inputs: AssemblyInputs) -> ContentSet: ...


async def _original(reports: Reports, location: str | None) -> SourceReport | None:
    if location is None or not ORIGINAL_LOCATION.fullmatch(location):
        return None
    return await read_report(reports, location, SourceReport)


async def _attribution(reports: Reports, location: str | None) -> SourceAttribution | None:
    if location is None or not ATTRIBUTION_LOCATION.fullmatch(location):
        return None
    return await read_report(reports, location, SourceAttribution)


async def _heartbeat() -> None:
    while True:
        if activity.in_activity():
            activity.heartbeat()
        await asyncio.sleep(HEARTBEAT_SECONDS)


def _failed(code: str, started: float) -> ContentAssemblyActivityResult:
    elapsed = int((time.monotonic() - started) * 1000)
    return ContentAssemblyActivityResult(
        failure=code,
        events=[
            SourceProgressEvent(
                kind="stage.failed",
                payload={
                    "stage": "assembly",
                    "status": "failed",
                    "reason": code,
                    "elapsed_ms": elapsed,
                },
            )
        ],
    )


async def _run(
    input_: ContentAssemblyActivityInput,
    artifact_root: Path,
    assembler: Assembler,
    reports: Reports,
    *,
    media: MediaStore | None = None,
    scratch_dir: Path | None = None,
) -> ContentAssemblyActivityResult:
    started = time.monotonic()
    folder = PurePosixPath("reports") / input_.workflow_id
    report = await read_report(reports, (folder / REPORT_FILE).as_posix(), SourceReport)
    if report is None:
        logger.warning("content assembly skipped; no stage 3 report for this workflow")
        return _failed("source_report_missing", started)

    attribution = await _attribution(reports, input_.attribution)
    original = await _original(reports, input_.original_report)
    store = media or LocalMediaStore(artifact_root)
    async with heartbeating(_heartbeat), MediaScratch(store, scratch_dir) as scratch:
        # The main is the post or, when attribution replaced it, the original.
        await scratch.pull([*media_locations(report), *media_locations(original)])
        inputs = AssemblyInputs(
            workflow_id=input_.workflow_id,
            report=report,
            attribution=attribution,
            original=original,
            artifact_root=scratch.root,
        )
        try:
            content_set = await assembler.build(inputs)
        except AssemblyError as error:
            logger.warning("content assembly failed: %s", error.code)
            return _failed(error.code, started)

    content = content_set.model_dump_json(indent=2).encode("utf-8")
    location = folder / CONTENT_SET_FILE
    await asyncio.to_thread(reports.put, location.as_posix(), "content_set", content)
    digest = sha256(content).hexdigest()
    ocr = content_set.main.ocr
    return ContentAssemblyActivityResult(
        content_set=ArtifactRef(
            artifact_id=f"art_content_set_{digest[:20]}",
            kind="content_set",
            label="Content set",
            media_type="application/json",
            location=location.as_posix(),
            checksum=f"sha256:{digest}",
            size_bytes=len(content),
        ),
        events=[
            SourceProgressEvent(
                kind="stage.completed",
                payload={
                    "stage": "assembly",
                    "status": "succeeded",
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                    "ocr_outcome": ocr.outcome if ocr is not None else "none",
                    "comment_count": len(content_set.comments),
                    "figure_count": len(content_set.figures),
                    "footage_count": len(content_set.footage),
                },
            )
        ],
    )


def build_production_assembler(settings: Settings) -> Assembler:
    from thoth_control_plane.assembly.adapters.captions import AgnoCaptionJudge
    from thoth_control_plane.assembly.adapters.figures import AgnoFigureModel
    from thoth_control_plane.assembly.adapters.region import FfmpegRegionTracker
    from thoth_control_plane.assembly.service import AssemblyPorts, ContentAssembler
    from thoth_control_plane.attribution.adapters.frames import FfmpegFrameSource, FfprobeDuration
    from thoth_control_plane.attribution.adapters.ocr import RapidOcrReader
    from thoth_control_plane.infrastructure.footage_store import FootageStore

    openrouter = settings.openrouter_api_key
    return ContentAssembler(
        AssemblyPorts(
            frames=FfmpegFrameSource(settings.THOTH_FFMPEG),
            probe=FfprobeDuration(settings.THOTH_FFPROBE),
            text=RapidOcrReader(angle=False),
            figures=AgnoFigureModel(openrouter, settings.THOTH_FIGURES_MODEL)
            if openrouter
            else None,
            tracker=FfmpegRegionTracker(settings.THOTH_FFMPEG),
            judge=AgnoCaptionJudge(openrouter, settings.THOTH_SOURCE_VISION_MODEL)
            if openrouter
            else None,
            footage=FootageStore.connect(settings.THOTH_EDITOR_DATABASE_URL.get_secret_value())
            if settings.THOTH_FOOTAGE_ENABLED and settings.THOTH_EDITOR_DATABASE_URL is not None
            else None,
        ),
        max_frames=settings.THOTH_SUBTITLE_OCR_MAX_FRAMES,
    )


@activity.defn(name="assemble_content")
async def assemble_content(input_: ContentAssemblyActivityInput) -> ContentAssemblyActivityResult:
    """Activity-name reference for workflow definitions and direct local use."""
    configured = build_content_assembly_activity(Settings())  # type: ignore[call-arg]
    return await configured(input_)


def build_content_assembly_activity(
    settings: Settings,
    *,
    assembler: Assembler | None = None,
    reports: Reports | None = None,
    media: MediaStore | None = None,
) -> Callable[[ContentAssemblyActivityInput], Awaitable[ContentAssemblyActivityResult]]:
    artifact_root = settings.THOTH_CONTROL_PLANE_ARTIFACT_ROOT.resolve()
    selected = assembler or build_production_assembler(settings)
    selected_reports = reports or connect_reports(settings)
    selected_media = media or build_media_store(settings)
    scratch_dir = settings.THOTH_MEDIA_SCRATCH_DIR

    @activity.defn(name="assemble_content")
    async def configured_content_assembly_activity(
        input_: ContentAssemblyActivityInput,
    ) -> ContentAssemblyActivityResult:
        return await _run(
            input_,
            artifact_root,
            selected,
            selected_reports,
            media=selected_media,
            scratch_dir=scratch_dir,
        )

    return configured_content_assembly_activity
