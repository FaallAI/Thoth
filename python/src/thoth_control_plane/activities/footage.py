"""The `build_footage` activity: footage for one workflow from its persisted reports.

It reads `reports/<workflow_id>/source-report.json`, the attribution and the original's report
the workflow passes, and runs the footage builder; state lives in PostgreSQL, clips under
`reports/<workflow_id>/footage/`. Only IDs, a status, counts, and elapsed milliseconds reach
Temporal history.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import time
from collections.abc import Awaitable, Callable
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Annotated, Any, Literal, Protocol

from pydantic import Field
from temporalio import activity
from temporalio.exceptions import ApplicationError

from thoth_control_plane.acquisition.models import SourceReport
from thoth_control_plane.activities.content_assembly import (
    REPORT_FILE,
    _attribution,
    _heartbeat,
    _original,
)
from thoth_control_plane.activities.media_scratch import (
    MediaScratch,
    heartbeating,
    media_locations,
)
from thoth_control_plane.config import Settings
from thoth_control_plane.domain.models import OpaqueId, SourceProgressEvent, StrictModel
from thoth_control_plane.footage.models import FootageResult
from thoth_control_plane.footage.service import FootageBuilder, FootageInputs, main_report
from thoth_control_plane.infrastructure.media_store import (
    LocalMediaStore,
    MediaStore,
    build_media_store,
)
from thoth_control_plane.infrastructure.report_store import Reports, connect_reports, read_report

if TYPE_CHECKING:
    from thoth_control_plane.footage.faces import Face

logger = logging.getLogger(__name__)
_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
# Under the 90 s clip budget: three workers queue on one TikWm gate (2026-11-27).
FOOTAGE_TIKWM_TIMEOUT = 20.0


class FootageActivityInput(StrictModel):
    workflow_id: OpaqueId
    attribution: str | None = None
    original_report: str | None = None
    # Spec 2026-11-15, 10.12: the chosen subject's face template (`encode_template`), and
    # whether clips must show it.
    subject: str | None = None
    face_check: bool = False


class SubjectChoice(StrictModel):
    """One face group of the main the operator may pick when the subject is doubtful."""

    choice_id: str
    image: str  # a JPEG data URI of one of the group's faces
    seconds: int
    template: str


class SubjectResult(StrictModel):
    """The main's subject by face: `clear` carries the template, `doubtful` the choices, and
    `none` turns the face check off (no faces, no main video, or no reader)."""

    status: Literal["clear", "doubtful", "none"]
    subject: str | None = None
    choices: list[SubjectChoice] = Field(default_factory=list)


class FootageActivityResult(StrictModel):
    footage_status: Literal["ok", "none", "disabled", "unavailable"]
    footage_count: Annotated[int, Field(ge=0, le=MAX_FOOTAGE)] = 0
    events: list[SourceProgressEvent] = Field(default_factory=list)


class Builder(Protocol):
    async def build(self, inputs: FootageInputs) -> FootageResult: ...


MAX_FOOTAGE = 8  # spec 2026-11-15, 10.6


def _done(status: str, count: int, started: float) -> FootageActivityResult:
    if count > MAX_FOOTAGE:
        logger.warning("footage count above the cap; clamped")
        count = MAX_FOOTAGE
    return FootageActivityResult(
        footage_status=status,  # type: ignore[arg-type]
        footage_count=count,
        events=[
            SourceProgressEvent(
                kind="stage.completed",
                payload={
                    "stage": "footage",
                    "status": "succeeded",
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                    "footage_status": status,
                    "footage_count": count,
                },
            )
        ],
    )


async def _run(
    input_: FootageActivityInput,
    artifact_root: Path,
    builder: Builder | None,
    reports: Reports,
    *,
    media: MediaStore | None = None,
    scratch_dir: Path | None = None,
) -> FootageActivityResult:
    started = time.monotonic()
    if builder is None:
        return _done("disabled", 0, started)
    folder = PurePosixPath("reports") / input_.workflow_id
    report = await read_report(reports, (folder / REPORT_FILE).as_posix(), SourceReport)
    if report is None:
        logger.warning("footage skipped; no stage 3 report for this workflow")
        return _done("unavailable", 0, started)
    # Read before the try: a store outage must propagate as itself, not as a builder failure.
    attribution = await _attribution(reports, input_.attribution)
    original = await _original(reports, input_.original_report)
    store = media or LocalMediaStore(artifact_root)
    clips = f"reports/{input_.workflow_id}/footage/"
    # The TikTok page card the creator listing cropped (spec 5c-2); the clips and photos live
    # under `clips`.
    page = f"reports/{input_.workflow_id}/cards/profile-page.png"
    async with heartbeating(_heartbeat), MediaScratch(store, scratch_dir) as scratch:
        # The post's and the original's media, and every clip, photo and page card an earlier
        # attempt stored.
        stored_clips = await asyncio.to_thread(store.list, clips)
        cards = await asyncio.to_thread(store.list, page.rsplit("/", 1)[0] + "/")
        stored_page = [location for location in cards if location == page]
        await scratch.pull(
            [*media_locations(report), *media_locations(original), *stored_clips, *stored_page]
        )

        async def publish(admitted: list[str]) -> None:
            # A carousel slide is the acquisition's own media, already stored.
            await scratch.push(
                location for location in admitted if location.startswith(clips) or location == page
            )

        # numpy stays out of the API's imports: the face helpers load in the worker only.
        from thoth_control_plane.footage.faces import decode_template

        inputs = FootageInputs(
            workflow_id=input_.workflow_id,
            report=report,
            attribution=attribution,
            original=original,
            artifact_root=scratch.root,
            publish=publish,
            subject=(
                decode_template(input_.subject)
                if input_.face_check and input_.subject is not None
                else None
            ),
            face_check=input_.face_check and input_.subject is not None,
        )
        try:
            result = await builder.build(inputs)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # Only a code reaches Temporal history: errors may carry URLs, captions or SQL
            # parameters.
            code = getattr(error, "code", None)
            if not isinstance(code, str) or not _CODE.fullmatch(code):
                code = "footage_failed"
            logger.warning("footage failed: %s", code)
            raise ApplicationError(code, type="FootageFailed") from None
    return _done(result.status, result.admitted, started)


class FaceFinder(Protocol):
    def faces(
        self, path: Path, start: float = 0.0, duration: float | None = None
    ) -> list[Face]: ...


def _choice(index: int, group: Any) -> SubjectChoice:
    from thoth_control_plane.footage.faces import encode_template, template

    middle = sorted(group.members, key=lambda face: face.second)[len(group.members) // 2]
    image = "data:image/jpeg;base64," + base64.b64encode(middle.crop).decode("ascii")
    return SubjectChoice(
        choice_id=f"g{index}",
        image=image,
        seconds=group.seconds,
        template=encode_template(template(group)),
    )


async def _find(
    input_: FootageActivityInput,
    faces: FaceFinder | None,
    reports: Reports,
    media: MediaStore,
    scratch_dir: Path | None,
) -> SubjectResult:
    """The subject by face (spec 2026-11-15, 10.12): the main's face groups by screen time."""
    from thoth_control_plane.footage.faces import (
        MAIN_SECONDS,
        MAX_CHOICES,
        clear_subject,
        encode_template,
        group_faces,
        template,
    )

    if faces is None:
        return SubjectResult(status="none")
    folder = PurePosixPath("reports") / input_.workflow_id
    report = await read_report(reports, (folder / REPORT_FILE).as_posix(), SourceReport)
    if report is None:
        return SubjectResult(status="none")
    attribution = await _attribution(reports, input_.attribution)
    original = await _original(reports, input_.original_report)
    main = main_report(
        FootageInputs(
            workflow_id=input_.workflow_id,
            report=report,
            attribution=attribution,
            original=original,
            artifact_root=Path("."),
        )
    )
    videos = [str(item.location) for item in main.media if item.kind == "video"]
    if not videos:
        return SubjectResult(status="none")
    async with heartbeating(_heartbeat), MediaScratch(media, scratch_dir) as scratch:
        await scratch.pull(videos[:1])
        found = await asyncio.to_thread(faces.faces, scratch.root / videos[0], 0.0, MAIN_SECONDS)
        # Off the event loop: the grouping is O(n^2) (final review, 3).
        groups = await asyncio.to_thread(group_faces, found)
    logger.info(
        "footage subject faces=%d groups=%s", len(found), [group.seconds for group in groups[:4]]
    )
    if not groups:
        return SubjectResult(status="none")
    clear = clear_subject(groups)
    if clear is not None:
        return SubjectResult(status="clear", subject=encode_template(template(clear)))
    return SubjectResult(
        status="doubtful",
        choices=[_choice(index, group) for index, group in enumerate(groups[:MAX_CHOICES])],
    )


@activity.defn(name="find_subject")
async def find_subject(input_: FootageActivityInput) -> SubjectResult:
    """Activity-name reference for workflow definitions."""
    configured = build_subject_activity(Settings())  # type: ignore[call-arg]
    return await configured(input_)


def build_subject_activity(
    settings: Settings,
    *,
    faces: FaceFinder | None = None,
    reports: Reports | None = None,
    media: MediaStore | None = None,
) -> Callable[[FootageActivityInput], Awaitable[SubjectResult]]:
    selected = faces
    if selected is None and settings.THOTH_FOOTAGE_ENABLED:
        from thoth_control_plane.footage.adapters.faces import shared_reader

        selected = shared_reader(settings.THOTH_FACE_MODELS_DIR)  # missing models raise here
    selected_reports = reports or connect_reports(settings)
    selected_media = media or build_media_store(settings)
    scratch_dir = settings.THOTH_MEDIA_SCRATCH_DIR

    @activity.defn(name="find_subject")
    async def configured_subject_activity(input_: FootageActivityInput) -> SubjectResult:
        return await _find(input_, selected, selected_reports, selected_media, scratch_dir)

    return configured_subject_activity


async def _tiktok_direct_url(url: str) -> str:
    import httpx

    from thoth_control_plane.acquisition.adapters.tikwm import TikWmResolver

    async with httpx.AsyncClient(timeout=FOOTAGE_TIKWM_TIMEOUT) as client:
        resolver = TikWmResolver(client, timeout_seconds=FOOTAGE_TIKWM_TIMEOUT)
        return (await resolver.resolve(url)).media.ephemeral_url.get_secret_value()


def context_ports(settings: Settings, key: str, media: MediaStore) -> dict[str, object]:
    """The footage library's ports (spec 2026-11-15): the card model with the query model as its
    fallback, long videos' captions, and a copy of a library clip's stored media."""
    from thoth_control_plane.acquisition.youtube_service import YtDlpClient
    from thoth_control_plane.footage.adapters.captions import YtDlpCaptionFetcher
    from thoth_control_plane.footage.adapters.context_model import OpenRouterCardModel

    async def library_media(location: str, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(media.fetch, location, target)

    return {
        "card": OpenRouterCardModel(
            key, [settings.THOTH_FOOTAGE_CARD_MODEL, settings.THOTH_FOOTAGE_QUERY_MODEL]
        ),
        "captions_text": YtDlpCaptionFetcher(YtDlpClient()),
        "library_media": library_media,
    }


def build_production_footage(settings: Settings) -> FootageBuilder:
    from thoth_control_plane.activities.source_investigation import (
        _account_profiles,
        _account_store,
    )
    from thoth_control_plane.assembly.adapters.captions import AgnoCaptionJudge
    from thoth_control_plane.assembly.adapters.region import FfmpegRegionTracker
    from thoth_control_plane.attribution.adapters.discovery import (
        DEFAULT_FACTORIES,
        ProfileDiscoverer,
        StoreLeases,
    )
    from thoth_control_plane.attribution.adapters.frames import FfmpegFrameSource, FfprobeDuration
    from thoth_control_plane.attribution.adapters.ocr import RapidOcrReader
    from thoth_control_plane.attribution.adapters.visual import OrbMatcher
    from thoth_control_plane.footage.adapters.creator import CreatorListings
    from thoth_control_plane.footage.adapters.downloader import YtDlpClipDownloader
    from thoth_control_plane.footage.adapters.embedder import OnnxEmbedder
    from thoth_control_plane.footage.adapters.faces import shared_reader
    from thoth_control_plane.footage.adapters.photos import HttpPhotoFetcher
    from thoth_control_plane.footage.adapters.queries import AgnoQueryModel
    from thoth_control_plane.footage.adapters.search import build_platform_search
    from thoth_control_plane.footage.adapters.vision import AgnoFootageJudge
    from thoth_control_plane.footage.recording import RECORDING_WIDTH
    from thoth_control_plane.footage.service import FootagePorts
    from thoth_control_plane.infrastructure.footage_store import FootageStore

    key = settings.openrouter_api_key
    database = settings.THOTH_EDITOR_DATABASE_URL
    if key is None or database is None:
        raise RuntimeError("footage needs the OpenRouter key and the editor database")
    accounts = _account_store(settings)
    leases = StoreLeases(accounts, _account_profiles(settings)) if accounts is not None else None
    return FootageBuilder(
        FootagePorts(
            queries=AgnoQueryModel(key, settings.THOTH_FOOTAGE_QUERY_MODEL),
            search=build_platform_search(leases),
            embedder=OnnxEmbedder(settings.THOTH_EMBEDDING_MODEL_DIR),
            downloader=YtDlpClipDownloader(
                settings.THOTH_FFMPEG, resolve_tiktok=_tiktok_direct_url
            ),
            frames=FfmpegFrameSource(settings.THOTH_FFMPEG),
            probe=FfprobeDuration(settings.THOTH_FFPROBE),
            text=RapidOcrReader(angle=False),
            judge=AgnoFootageJudge(key, settings.THOTH_SOURCE_VISION_MODEL),
            store=FootageStore.connect(database.get_secret_value()),
            tracker=FfmpegRegionTracker(settings.THOTH_FFMPEG),
            captions=AgnoCaptionJudge(key, settings.THOTH_SOURCE_VISION_MODEL),
            # Spec 5c-2: the creator's own videos, photos and page card, under the same
            # account access policy as every other listing.
            creator=CreatorListings(ProfileDiscoverer(DEFAULT_FACTORIES, leases=leases)),
            photos=HttpPhotoFetcher(),
            # One copy of a recording (spec 2026-11-15, 9.9): 1 fps at 480 px, ORB in time.
            recording_frames=FfmpegFrameSource(settings.THOTH_FFMPEG, width=RECORDING_WIDTH),
            matcher=OrbMatcher(step=1),
            # The story's subject by face (spec 2026-11-15, 10.12).
            faces=shared_reader(settings.THOTH_FACE_MODELS_DIR),
            **context_ports(settings, key, build_media_store(settings)),  # type: ignore[arg-type]
        ),
        # The curated JSON list is not a filter (operator, 2026-10-31).
        aggregators=frozenset(),
        story_min=settings.THOTH_FOOTAGE_STORY_MIN,
        max_frames=settings.THOTH_SUBTITLE_OCR_MAX_FRAMES,
        context_enabled=settings.THOTH_FOOTAGE_CONTEXT_ENABLED,
    )


@activity.defn(name="build_footage")
async def build_footage(input_: FootageActivityInput) -> FootageActivityResult:
    """Activity-name reference for workflow definitions and direct local use."""
    configured = build_footage_activity(Settings())  # type: ignore[call-arg]
    return await configured(input_)


def build_footage_activity(
    settings: Settings,
    *,
    builder: Builder | None = None,
    reports: Reports | None = None,
    media: MediaStore | None = None,
) -> Callable[[FootageActivityInput], Awaitable[FootageActivityResult]]:
    artifact_root = settings.THOTH_CONTROL_PLANE_ARTIFACT_ROOT.resolve()
    selected = builder or (
        build_production_footage(settings) if settings.THOTH_FOOTAGE_ENABLED else None
    )
    selected_reports = reports or connect_reports(settings)
    selected_media = media or build_media_store(settings)
    scratch_dir = settings.THOTH_MEDIA_SCRATCH_DIR

    @activity.defn(name="build_footage")
    async def configured_footage_activity(input_: FootageActivityInput) -> FootageActivityResult:
        return await _run(
            input_,
            artifact_root,
            selected,
            selected_reports,
            media=selected_media,
            scratch_dir=scratch_dir,
        )

    return configured_footage_activity
