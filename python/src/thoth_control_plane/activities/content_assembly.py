"""The `assemble_content` activity: build the Content Set from the persisted reports.

It reads `reports/<workflow_id>/source-report.json`, the attribution beside it when present,
and the original's report at the location the workflow passes, runs the assembler, and writes
`reports/<workflow_id>/content-set.json` atomically. A required part that fails returns its
reason code; nothing is written. Only IDs, codes, counts, and elapsed milliseconds reach
Temporal history.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import time
from collections.abc import Awaitable, Callable
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Annotated, Protocol

from pydantic import Field, model_validator
from temporalio import activity

from thoth_control_plane.acquisition.models import SourceReport
from thoth_control_plane.assembly.models import ContentSet
from thoth_control_plane.assembly.ports import AssemblyError
from thoth_control_plane.assembly.service import AssemblyInputs
from thoth_control_plane.attribution.models import SourceAttribution
from thoth_control_plane.config import Settings
from thoth_control_plane.domain import ArtifactRef
from thoth_control_plane.domain.models import OpaqueId, SourceProgressEvent, StrictModel

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


def _write(path: Path, content: bytes) -> None:
    part = path.with_name(path.name + ".part")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        part.write_bytes(content)
        os.replace(part, path)
    finally:
        part.unlink(missing_ok=True)


def _original(root: Path, location: str | None) -> SourceReport | None:
    if location is None or not ORIGINAL_LOCATION.fullmatch(location):
        return None
    try:
        return SourceReport.model_validate_json((root / location).read_bytes())
    except (OSError, ValueError):
        return None


def _attribution(root: Path, location: str | None) -> SourceAttribution | None:
    if location is None or not ATTRIBUTION_LOCATION.fullmatch(location):
        return None
    try:
        return SourceAttribution.model_validate_json((root / location).read_bytes())
    except (OSError, ValueError):
        return None


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
    input_: ContentAssemblyActivityInput, artifact_root: Path, assembler: Assembler
) -> ContentAssemblyActivityResult:
    started = time.monotonic()
    folder = PurePosixPath("reports") / input_.workflow_id
    try:
        report = SourceReport.model_validate_json(
            (artifact_root / folder / REPORT_FILE).read_bytes()
        )
    except (OSError, ValueError):
        logger.warning("content assembly skipped; no stage 3 report for this workflow")
        return _failed("source_report_missing", started)

    inputs = AssemblyInputs(
        workflow_id=input_.workflow_id,
        report=report,
        attribution=_attribution(artifact_root, input_.attribution),
        original=_original(artifact_root, input_.original_report),
        artifact_root=artifact_root,
    )
    heartbeat = asyncio.create_task(_heartbeat())
    try:
        content_set = await assembler.build(inputs)
    except AssemblyError as error:
        logger.warning("content assembly failed: %s", error.code)
        return _failed(error.code, started)
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat

    content = content_set.model_dump_json(indent=2).encode("utf-8")
    location = folder / CONTENT_SET_FILE
    try:
        _write(artifact_root / location, content)
    except OSError:
        logger.warning("content set could not be written")
        return _failed("artifact_write_failed", started)
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
                },
            )
        ],
    )


def build_production_assembler(settings: Settings) -> Assembler:
    from thoth_control_plane.assembly.adapters.figures import AgnoFigureModel
    from thoth_control_plane.assembly.service import AssemblyPorts, ContentAssembler
    from thoth_control_plane.attribution.adapters.frames import FfmpegFrameSource, FfprobeDuration
    from thoth_control_plane.attribution.adapters.ocr import RapidOcrReader

    openrouter = settings.openrouter_api_key
    return ContentAssembler(
        AssemblyPorts(
            frames=FfmpegFrameSource(settings.THOTH_FFMPEG),
            probe=FfprobeDuration(settings.THOTH_FFPROBE),
            text=RapidOcrReader(angle=False),
            figures=AgnoFigureModel(openrouter, settings.THOTH_FIGURES_MODEL)
            if openrouter
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
    settings: Settings, *, assembler: Assembler | None = None
) -> Callable[[ContentAssemblyActivityInput], Awaitable[ContentAssemblyActivityResult]]:
    artifact_root = settings.THOTH_CONTROL_PLANE_ARTIFACT_ROOT.resolve()
    selected = assembler or build_production_assembler(settings)

    @activity.defn(name="assemble_content")
    async def configured_content_assembly_activity(
        input_: ContentAssemblyActivityInput,
    ) -> ContentAssemblyActivityResult:
        return await _run(input_, artifact_root, selected)

    return configured_content_assembly_activity
