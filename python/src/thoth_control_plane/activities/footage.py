"""The `build_footage` activity: footage for one workflow from its persisted reports.

It reads `reports/<workflow_id>/source-report.json`, the attribution and the original's report
the workflow passes, and runs the footage builder; state lives in PostgreSQL, clips under
`reports/<workflow_id>/footage/`. Only IDs, a status, counts, and elapsed milliseconds reach
Temporal history.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Protocol

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
from thoth_control_plane.footage.service import FootageBuilder, FootageInputs
from thoth_control_plane.infrastructure.media_store import (
    LocalMediaStore,
    MediaStore,
    build_media_store,
)
from thoth_control_plane.infrastructure.report_store import Reports, connect_reports, read_report

logger = logging.getLogger(__name__)
_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class FootageActivityInput(StrictModel):
    workflow_id: OpaqueId
    attribution: str | None = None
    original_report: str | None = None


class FootageActivityResult(StrictModel):
    footage_status: Literal["ok", "none", "disabled", "unavailable"]
    footage_count: Annotated[int, Field(ge=0, le=MAX_FOOTAGE)] = 0
    events: list[SourceProgressEvent] = Field(default_factory=list)


class Builder(Protocol):
    async def build(self, inputs: FootageInputs) -> FootageResult: ...


MAX_FOOTAGE = 6


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
    async with heartbeating(_heartbeat), MediaScratch(store, scratch_dir) as scratch:
        # The post's and the original's media, and every clip an earlier attempt admitted.
        stored_clips = await asyncio.to_thread(store.list, clips)
        await scratch.pull([*media_locations(report), *media_locations(original), *stored_clips])

        async def publish() -> None:
            made = (scratch.root / clips).glob("*.mp4")
            await scratch.push(f"{clips}{path.name}" for path in sorted(made) if path.is_file())

        inputs = FootageInputs(
            workflow_id=input_.workflow_id,
            report=report,
            attribution=attribution,
            original=original,
            artifact_root=scratch.root,
            publish=publish,
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


async def _tiktok_direct_url(url: str) -> str:
    import httpx

    from thoth_control_plane.acquisition.adapters.tikwm import TikWmResolver

    async with httpx.AsyncClient(timeout=30.0) as client:
        return (await TikWmResolver(client).resolve(url)).media.ephemeral_url.get_secret_value()


def build_production_footage(settings: Settings) -> FootageBuilder:
    from thoth_control_plane.activities.source_investigation import (
        _account_profiles,
        _account_store,
    )
    from thoth_control_plane.assembly.adapters.captions import AgnoCaptionJudge
    from thoth_control_plane.assembly.adapters.region import FfmpegRegionTracker
    from thoth_control_plane.attribution.adapters.discovery import StoreLeases
    from thoth_control_plane.attribution.adapters.frames import FfmpegFrameSource, FfprobeDuration
    from thoth_control_plane.attribution.adapters.ocr import RapidOcrReader
    from thoth_control_plane.attribution.candidates import load_curated
    from thoth_control_plane.footage.adapters.downloader import YtDlpClipDownloader
    from thoth_control_plane.footage.adapters.embedder import OnnxEmbedder
    from thoth_control_plane.footage.adapters.queries import AgnoQueryModel
    from thoth_control_plane.footage.adapters.search import build_platform_search
    from thoth_control_plane.footage.adapters.vision import AgnoFootageJudge
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
        ),
        aggregators=load_curated(),
        story_min=settings.THOTH_FOOTAGE_STORY_MIN,
        max_frames=settings.THOTH_SUBTITLE_OCR_MAX_FRAMES,
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
