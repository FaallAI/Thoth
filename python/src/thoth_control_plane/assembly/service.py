"""Build the Content Set of one workflow: main and its final OCR, comments, figures.

The main is the original when attribution replaced the post, else the post itself. Figures run
alongside the OCR (they never read it). Comments and figures degrade; the main, its OCR, and
validation are required and raise `AssemblyError` with a reason code.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol

from pydantic import ValidationError

from thoth_control_plane.acquisition.models import CardArtifact, MaterializedMedia, SourceReport
from thoth_control_plane.assembly.comments import card_ref, merge_comments, post_card_ref
from thoth_control_plane.assembly.figures import figure_prompt, normalize_figures
from thoth_control_plane.assembly.models import (
    MAX_FOOTAGE,
    MAX_PHOTOS,
    ContentSet,
    Figure,
    Footage,
    FootageStatus,
    Main,
    MainOcr,
    MediaRef,
    Photo,
)
from thoth_control_plane.assembly.ocr import analyze_main_ocr
from thoth_control_plane.assembly.ports import (
    AssemblyError,
    CaptionJudge,
    DurationProbe,
    FigureModel,
    FrameSampler,
    RegionTracker,
    TextReader,
)
from thoth_control_plane.attribution.models import SourceAttribution

logger = logging.getLogger(__name__)
HEADLINE_PREFIX = "headline: "
FiguresStatus = Literal["ok", "none", "unavailable"]


class FootageReader(Protocol):
    def run(self, workflow_id: str) -> Any: ...
    def admitted(self, workflow_id: str) -> list[Any]: ...


@dataclass(frozen=True)
class AssemblyPorts:
    frames: FrameSampler
    probe: DurationProbe
    text: TextReader
    figures: FigureModel | None = None
    tracker: RegionTracker | None = None
    judge: CaptionJudge | None = None
    footage: FootageReader | None = None


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
        "profile_page": card_ref(report.profile_page),
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
    if fields["kind"] != "card":
        # A text-only post's card already is the main (spec 5c-2, G1).
        fields["post_card"] = post_card_ref(report.post_card)
    return fields


def _headline(attribution: SourceAttribution | None) -> str:
    for item in attribution.evidence if attribution is not None else []:
        if item.kind == "cover_vision" and item.detail.startswith(HEADLINE_PREFIX):
            return item.detail[len(HEADLINE_PREFIX) :]
    return ""


def _footage_item(view: Any) -> Footage | None:
    try:
        return Footage(
            source=view.source,
            url=view.url,
            platform=view.platform,
            owner_handle=view.owner_handle,
            published_at=view.published_at,
            engagement=view.engagement,
            query=view.query,
            visual=view.visual,
            caption=view.caption[:2000],
            description=(view.description or "")[:300],
            video=MediaRef(
                location=PurePosixPath(view.media_location),
                media_type="video/mp4",
                checksum=view.media_checksum,
                bytes=view.media_bytes,
                duration_seconds=view.clip_duration,
            ),
            clip_start=view.clip_start or 0.0,
            ocr=MainOcr.model_validate(view.ocr or {}, strict=False),  # jsonb holds a JSON dump
            story_score=min(1.0, max(0.0, view.story_score or 0.0)),
            shows_object=view.shows_object,
        )
    except (ValidationError, TypeError, ValueError):
        logger.warning("a stored footage clip failed validation; it is left out")
        return None


IMAGE_TYPES = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def _photo_item(view: Any) -> Photo | None:
    location = PurePosixPath(view.media_location or "")
    try:
        return Photo(
            source=view.source,
            url=view.url,
            platform=view.platform,
            owner_handle=view.owner_handle,
            caption=view.caption[:2000],
            image=MediaRef(
                location=location,
                media_type=IMAGE_TYPES.get(location.suffix, ""),
                checksum=view.media_checksum,
                bytes=view.media_bytes,
            ),
            story_score=min(1.0, max(0.0, view.story_score or 0.0)),
        )
    except (ValidationError, TypeError, ValueError):
        logger.warning("a stored creator photo failed validation; it is left out")
        return None


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
        footage, footage_status = await self._footage(inputs.workflow_id)
        photos, page = await self._creator(inputs.workflow_id)
        if fields["profile_page"] is None:
            # TikTok's page card comes from the footage run's creator listing (spec 5c-2).
            fields["profile_page"] = page
        figures_task = asyncio.create_task(
            self._figures(
                fields["title"],
                fields["description"],
                _headline(inputs.attribution),
                [item.description for item in footage],
            )
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
                    # A trim is for a main that may be a repost (amendment, 2026-10-12).
                    trim_allowed=source == "input" and verdict in ("unresolved", "none"),
                    tracker=self._ports.tracker,
                    judge=self._ports.judge,
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
                footage=footage,
                footage_status=footage_status,
                photos=photos,
            )
        except ValidationError:
            logger.warning("content set rejected by its validators")
            raise AssemblyError("content_set_invalid") from None

    async def _footage(self, workflow_id: str) -> tuple[list[Footage], FootageStatus]:
        reader = self._ports.footage
        if reader is None:
            return [], "disabled"
        try:
            run = await asyncio.to_thread(reader.run, workflow_id)
            views = await asyncio.to_thread(reader.admitted, workflow_id) if run else []
        except Exception:
            logger.warning("footage state unavailable; the content set continues without it")
            return [], "unavailable"
        if run is None or run.status != "done":
            return [], "unavailable"
        items = [item for item in (_footage_item(view) for view in views) if item is not None]
        if len(items) > MAX_FOOTAGE:
            logger.warning("footage over the cap: %d stored, keeping %d", len(items), MAX_FOOTAGE)
            items = items[:MAX_FOOTAGE]
        if run.footage_status == "ok":
            return items, "ok" if items else "none"
        return [], run.footage_status or "unavailable"

    async def _creator(self, workflow_id: str) -> tuple[list[Photo], MediaRef | None]:
        """The creator photos and the page card a finished footage run kept (spec 5c-2)."""
        reader = self._ports.footage
        if reader is None:
            return [], None
        try:
            run = await asyncio.to_thread(reader.run, workflow_id)
            if run is None or run.status != "done":
                return [], None
            views = await asyncio.to_thread(reader.admitted, workflow_id, "image")
        except Exception:
            logger.warning("creator photos unavailable; the content set continues without them")
            return [], None
        photos = [item for item in (_photo_item(view) for view in views) if item is not None]
        page = None
        if run.profile_page is not None:
            try:
                page = card_ref(CardArtifact.model_validate(run.profile_page, strict=False))
            except ValidationError:
                logger.warning("a stored page card failed validation; it is left out")
        return photos[:MAX_PHOTOS], page

    async def _figures(
        self, title: str, description: str, headline: str, footage: Sequence[str] = ()
    ) -> tuple[list[Figure], FiguresStatus]:
        prompt = figure_prompt(title, description, headline, footage)
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
