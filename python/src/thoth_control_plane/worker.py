"""Temporal worker entry point for the Python control plane."""

from __future__ import annotations

import asyncio
import importlib
import logging
import shutil
from collections.abc import Mapping
from importlib.util import find_spec
from typing import Any

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker
from temporalio.worker._worker import load_default_build_id

from thoth_control_plane import metering, progress
from thoth_control_plane.acquisition.accounts.profiles import sweep_unsealed
from thoth_control_plane.acquisition.browser import ScraplingCapability, check_scrapling_capability
from thoth_control_plane.activities import (
    AcquisitionRunner,
    build_content_assembly_activity,
    build_source_attribution_activity,
    build_source_investigation_activity,
)
from thoth_control_plane.activities.footage import build_footage_activity
from thoth_control_plane.activities.meter_scope import (
    MeterScopeInterceptor,
    record_workflow_completed,
)
from thoth_control_plane.activities.narration import build_narration_activities
from thoth_control_plane.activities.progress_scope import ProgressScopeInterceptor
from thoth_control_plane.activities.prompt_proposal import (
    PROMPT_PROPOSAL_TASK_QUEUE,
    build_prompt_proposal_activity,
)
from thoth_control_plane.activities.story_assist import StoryAssistActivity
from thoth_control_plane.config import Settings, SettingsValidationError
from thoth_control_plane.footage.adapters.embedder import load_model
from thoth_control_plane.infrastructure.media_store import (
    MediaStore,
    MeteredMediaStore,
    build_media_store,
)
from thoth_control_plane.infrastructure.prompt_proposal_repository import (
    PostgresPromptProposalRepository,
)
from thoth_control_plane.infrastructure.prompt_provider import OpenAICompatiblePromptProvider
from thoth_control_plane.infrastructure.report_store import Reports, connect_reports
from thoth_control_plane.infrastructure.step_store import StepStore
from thoth_control_plane.infrastructure.temporal_gateway import TASK_QUEUE
from thoth_control_plane.infrastructure.usage_store import UsageStore
from thoth_control_plane.observability import (
    configure_logging,
    configure_provider_logging,
    watch_event_loop,
)
from thoth_control_plane.operations.yt_dlp_version import check_freshness
from thoth_control_plane.workflows import SourceInvestigationWorkflow
from thoth_control_plane.workflows.prompt_proposal import PromptProposalWorkflow
from thoth_control_plane.workflows.story_assist import StoryAssistWorkflow

logger = logging.getLogger(__name__)

# Adapters import these on first use, inside async activities, so the import runs on the event
# loop. agno with openai alone takes 1.3 s idle and stalled the loop 2.3 s under footage load,
# past Temporal's 2 s activation limit (TMPRL1101, 2026-10-16); import them before any activity.
HEAVY_MODULES = (
    "numpy",
    "cv2",
    "PIL.Image",
    "agno.agent",
    "agno.media",
    "agno.models.openai.like",
    "yt_dlp",
    "yt_dlp.utils",
    "onnxruntime",
    "tokenizers",
    "rapidocr",
    "faster_whisper",
    "sherpa_onnx",
    "minio",
)


def preload_heavy_modules() -> None:
    for name in HEAVY_MODULES:
        try:
            importlib.import_module(name)
        except ImportError:
            continue  # an optional extra; its adapter raises ToolMissing when used


def warm_up(settings: Settings) -> None:
    """Work that holds the GIL for a second or more, done before the loop serves Temporal."""
    load_default_build_id()  # memoized; `Worker()` would hash every loaded module on the loop
    if settings.THOTH_FOOTAGE_ENABLED:
        load_model(settings.THOTH_EMBEDDING_MODEL_DIR)


def check_media_store(settings: Settings) -> MediaStore:
    """Every activity reads or writes workflow media: an unreachable store stops the worker at
    startup, like a missing tool (spec 2026-10-17)."""
    store = build_media_store(settings)
    store.check()
    return store


def narration_registrations(narration: Any | None) -> tuple[list[Any], list[Any], list[Any]]:
    """The narration's workflows, its main-queue activities, and its prompt-queue activity
    (the script needs the provider credentials; spec 2026-10-31)."""
    if narration is None:
        return [], [], []
    from thoth_control_plane.workflows.narration import (
        NarrationRevoiceWorkflow,
        NarrationWorkflow,
    )

    return (
        [NarrationWorkflow, NarrationRevoiceWorkflow],
        [
            narration.transcribe,
            narration.voice,
            narration.write_draft,
            narration.revoice,
            narration.mark,
        ],
        [narration.write_script],
    )


def build_source_investigation_worker(
    client: Client,
    settings: Settings,
    *,
    runner: AcquisitionRunner | None = None,
    capability: ScraplingCapability | Mapping[str, object] | None = None,
    reports: Reports | None = None,
    media: MediaStore | None = None,
    narration: Any | None = None,
) -> Worker:
    """Register the production source activity with its configured artifact root."""
    reports = reports or connect_reports(settings)
    media = media or build_media_store(settings)
    narration_workflows, narration_activities, _ = narration_registrations(narration)
    return Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[SourceInvestigationWorkflow, *narration_workflows],
        activities=[
            *narration_activities,
            build_source_investigation_activity(
                settings, runner=runner, capability=capability, reports=reports, media=media
            ),
            build_source_attribution_activity(settings, reports=reports, media=media),
            build_content_assembly_activity(settings, reports=reports, media=media),
            build_footage_activity(settings, reports=reports, media=media),
            record_workflow_completed,
        ],
        interceptors=[MeterScopeInterceptor(client), ProgressScopeInterceptor()],
        max_concurrent_activities=1,
    )


def _require_media(settings: Settings) -> None:
    for code, binary in (
        ("ffmpeg_missing", settings.THOTH_FFMPEG),
        ("ffprobe_missing", settings.THOTH_FFPROBE),
    ):
        if shutil.which(binary) is None:
            raise SettingsValidationError(code)
    if find_spec("rapidocr") is None:
        raise SettingsValidationError("rapidocr_missing")
    if find_spec("cv2") is None:
        raise SettingsValidationError("opencv_missing")


def check_media_tools(settings: Settings) -> None:
    """Refuse to start without a tool, key, or model a stage on this worker needs.

    Operator, 2026-10-11 and 2026-10-13: a missing tool is an explicit error, never a silent
    degradation; vision and Jev are required for attribution.
    """
    from thoth_control_plane.attribution.adapters.speech import (
        DIARIZATION_FILES,
        WHISPER_FILES,
        missing,
    )

    # Every worker writes reports to the editor database.
    if settings.THOTH_EDITOR_DATABASE_URL is None:
        raise SettingsValidationError("editor_database_missing")
    if settings.THOTH_SOURCE_ATTRIBUTION_ENABLED:
        if settings.openrouter_api_key is None:
            raise SettingsValidationError("openrouter_key_missing")
        _require_media(settings)
        if find_spec("faster_whisper") is None:
            raise SettingsValidationError("whisper_missing")
        if missing(settings.THOTH_WHISPER_MODEL_DIR, WHISPER_FILES):
            raise SettingsValidationError("whisper_model_missing")
        if find_spec("PIL") is None:
            raise SettingsValidationError("pillow_missing")
        if find_spec("sherpa_onnx") is None:
            raise SettingsValidationError("diarization_missing")
        if missing(settings.THOTH_DIARIZATION_MODEL_DIR, DIARIZATION_FILES):
            raise SettingsValidationError("diarization_model_missing")
        # Spec 2026-10-13, 3.4: a platform switched to Camoufox must find it installed.
        if find_spec("camoufox") is None:
            raise SettingsValidationError("camoufox_missing")
    if settings.THOTH_CONTENT_ASSEMBLY_ENABLED:
        _require_media(settings)
    if settings.THOTH_FOOTAGE_ENABLED:
        from thoth_control_plane.footage.adapters.embedder import EMBEDDING_FILES

        if settings.openrouter_api_key is None:
            raise SettingsValidationError("openrouter_key_missing")
        _require_media(settings)
        if missing(settings.THOTH_EMBEDDING_MODEL_DIR, EMBEDDING_FILES):
            raise SettingsValidationError("embedding_model_missing")
        if find_spec("onnxruntime") is None or find_spec("tokenizers") is None:
            raise SettingsValidationError("embedding_runtime_missing")


def build_prompt_proposal_worker(
    client: Client, settings: Settings, *, narration: Any | None = None
) -> Worker:
    """Register the proposal activity on its dedicated queue with stored secrets."""
    catalog = settings.THOTH_PROMPT_PROVIDER_CATALOG
    enabled = tuple(provider for provider in catalog if provider.enabled)
    secrets = settings.prompt_provider_secrets
    missing = sum(provider.credential_id not in secrets for provider in enabled)
    if missing:
        # This worker shares the main worker's process, so a missing key must not stop every run:
        # the adapter refuses that provider per call. Never name the provider or credential.
        logger.warning("%d enabled prompt provider(s) lack a worker credential", missing)
    repository = PostgresPromptProposalRepository(
        settings.THOTH_EDITOR_DATABASE_URL.get_secret_value()
        if settings.THOTH_EDITOR_DATABASE_URL is not None
        else ""
    )
    provider_adapter = OpenAICompatiblePromptProvider(
        runtime_catalog=catalog,
        secrets=secrets,
    )
    activity = build_prompt_proposal_activity(repository=repository, provider=provider_adapter)
    # Story Assist shares the queue and the credentials (spec 2026-10-27, 7).
    assist = StoryAssistActivity(provider=provider_adapter)
    return Worker(
        client,
        task_queue=PROMPT_PROPOSAL_TASK_QUEUE,
        workflows=[PromptProposalWorkflow, StoryAssistWorkflow],
        activities=[activity.run, assist.run, *narration_registrations(narration)[2]],
        max_concurrent_activities=1,
    )


async def run_worker(settings: Settings | None = None) -> None:
    """Run the control-plane activities and the prompt workers."""
    runtime_settings = settings or Settings()  # type: ignore[call-arg]
    check_media_tools(runtime_settings)
    configure_logging()
    preload_heavy_modules()
    warm_up(runtime_settings)
    media = MeteredMediaStore(check_media_store(runtime_settings))
    # check_media_tools refused to start without the editor database.
    metering.install(
        UsageStore.connect(runtime_settings.THOTH_EDITOR_DATABASE_URL.get_secret_value())  # type: ignore[union-attr]
    )
    progress.install(
        StepStore.connect(runtime_settings.THOTH_EDITOR_DATABASE_URL.get_secret_value())  # type: ignore[union-attr]
    )
    sweep_unsealed()  # a killed worker may have left account profiles decrypted
    configure_provider_logging()
    capability = await check_scrapling_capability()
    # A stale yt-dlp fails YouTube extraction; warn once, in the background, never block.
    freshness = asyncio.create_task(check_freshness())
    watch = asyncio.create_task(watch_event_loop())
    try:
        client = await Client.connect(
            runtime_settings.THOTH_TEMPORAL_TARGET,
            namespace=runtime_settings.THOTH_TEMPORAL_NAMESPACE,
            data_converter=pydantic_data_converter,
        )
        reports = connect_reports(runtime_settings)
        # Auto-draft narration (spec 2026-10-31): one set of ports for both queues.
        narration = (
            build_narration_activities(runtime_settings, media)
            if runtime_settings.THOTH_EDITOR_DATABASE_URL is not None
            else None
        )
        async with (
            build_source_investigation_worker(
                client,
                runtime_settings,
                capability=capability,
                reports=reports,
                media=media,
                narration=narration,
            ),
            # Prompt Lab proposals and Story Assist; an empty catalog answers with failure codes.
            build_prompt_proposal_worker(client, runtime_settings, narration=narration),
        ):
            await asyncio.Future()
    finally:
        freshness.cancel()
        watch.cancel()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
