"""Build the Content Set of one workflow: main and its final OCR, comments, figures.

The main is the original when attribution replaced the post, else the post itself. Figures run
alongside the OCR (they never read it). Comments and figures degrade; the main, its OCR, and
validation are required and raise `AssemblyError` with a reason code.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from thoth_control_plane.acquisition.models import MaterializedMedia, SourceReport
from thoth_control_plane.assembly.comments import card_ref, merge_comments
from thoth_control_plane.assembly.figures import figure_prompt, normalize_figures
from thoth_control_plane.assembly.models import ContentSet, Figure, Main, MainOcr, MediaRef
from thoth_control_plane.assembly.ocr import analyze_main_ocr
from thoth_control_plane.assembly.ports import (
    AssemblyError,
    DurationProbe,
    FigureModel,
    FrameSampler,
    TextReader,
)
from thoth_control_plane.attribution.models import SourceAttribution

logger = logging.getLogger(__name__)
HEADLINE_PREFIX = "headline: "
FiguresStatus = Literal["ok", "none", "unavailable"]


@dataclass(frozen=True)
class AssemblyPorts:
    frames: FrameSampler
    probe: DurationProbe
    text: TextReader
    figures: FigureModel | None = None


@dataclass(frozen=True)
class AssemblyInputs:
    workflow_id: str
    report: SourceReport
    attribution: SourceAttribution | None
    original: SourceReport | None
    artifact_root: Path


def _media_ref(media: MaterializedMedia) -> MediaRef:
    return MediaRef(
        location=media.location,
        media_type=media.media_type,
        checksum=media.checksum,
        bytes=media.bytes,
        width=media.width,
        height=media.height,
        duration_seconds=media.duration_seconds,
    )


def _main_fields(report: SourceReport, source: Literal["input", "original"]) -> dict[str, Any]:
    text = report.post.text.strip()
    fields: dict[str, Any] = {
        "source": source,
        "url": report.source.canonical_url,
        "platform": report.source.platform,
        "title": text[:120],
        "description": text,
        "owner_handle": report.post.owner_handle,
        "published_at": report.post.published_at,
        "engagement": dict(report.post.engagement),
        "profile_card": card_ref(report.profile_card),
    }
    videos = [media for media in report.media if media.kind == "video"]
    images = [media for media in report.media if media.kind == "image"]
    if videos:
        fields.update(kind="video", video=_media_ref(videos[0]))
    elif images:
        fields.update(kind="images", images=[_media_ref(media) for media in images])
    elif report.post_card is not None:
        fields.update(kind="card", card=card_ref(report.post_card))
    else:
        raise AssemblyError("main_media_missing")
    return fields


def _headline(attribution: SourceAttribution | None) -> str:
    for item in attribution.evidence if attribution is not None else []:
        if item.kind == "cover_vision" and item.detail.startswith(HEADLINE_PREFIX):
            return item.detail[len(HEADLINE_PREFIX) :]
    return ""


def _video_path(root: Path, video: MediaRef) -> Path:
    base = root.resolve()
    path = (root / video.location).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        raise AssemblyError("main_media_missing")
    return path


class ContentAssembler:
    def __init__(
        self,
        ports: AssemblyPorts,
        *,
        max_frames: int = 12,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._ports = ports
        self._max_frames = max_frames
        self._clock = clock

    async def build(self, inputs: AssemblyInputs) -> ContentSet:
        verdict = inputs.attribution.verdict if inputs.attribution is not None else "none"
        if verdict == "replaced":
            if inputs.original is None:
                raise AssemblyError("original_report_missing")
            main_report, source = inputs.original, "original"
            sources = [("original", inputs.original), ("input", inputs.report)]
        else:
            main_report, source = inputs.report, "input"
            sources = [("input", inputs.report)]

        fields = _main_fields(main_report, source)  # type: ignore[arg-type]
        figures_task = asyncio.create_task(
            self._figures(fields["title"], fields["description"], _headline(inputs.attribution))
        )
        try:
            ocr: MainOcr | None = None
            if fields["kind"] == "video":
                video: MediaRef = fields["video"]
                ocr = await analyze_main_ocr(
                    _video_path(inputs.artifact_root, video),
                    video.duration_seconds,
                    frames=self._ports.frames,
                    probe=self._ports.probe,
                    text=self._ports.text,
                    max_frames=self._max_frames,
                    now=self._clock(),
                )
        except BaseException:
            figures_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await figures_task
            raise
        figures, status = await figures_task

        try:
            return ContentSet(
                workflow_id=inputs.workflow_id,
                attribution_verdict=verdict,
                main=Main(**fields, ocr=ocr),
                comments=merge_comments(sources),  # type: ignore[arg-type]
                figures=figures,
                figures_status=status,
            )
        except ValidationError:
            logger.warning("content set rejected by its validators")
            raise AssemblyError("content_set_invalid") from None

    async def _figures(
        self, title: str, description: str, headline: str
    ) -> tuple[list[Figure], FiguresStatus]:
        prompt = figure_prompt(title, description, headline)
        if prompt is None:
            return [], "none"
        if self._ports.figures is None:
            return [], "unavailable"
        try:
            answer = await self._ports.figures.read(prompt)
        except Exception:
            logger.warning("figures unavailable; the content set continues without them")
            return [], "unavailable"
        if answer is None:
            return [], "unavailable"
        figures = normalize_figures(answer)
        return figures, "ok" if figures else "none"
