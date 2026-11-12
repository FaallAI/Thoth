"""The narration activities: transcribe, write the script, voice it, write the draft (spec 5).

Each step records its state on the draft's narration row, so Studio shows where it is. Known
failures are recorded as a safe code and returned; anything else is raised for Temporal's retry.
Nothing here voices a beat before the workflow has the operator's approval: the workflow only
calls `narration_voice` after it.
"""

from __future__ import annotations

import asyncio
import logging
import math
import tempfile
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from temporalio import activity

from thoth_control_plane import metering
from thoth_control_plane.activities.prompt_proposal import _safe_failure_code
from thoth_control_plane.application.narration_script import (
    STAGE,
    ScriptInvalid,
    build_script_request,
    facts_from_materials,
    parse_script,
    supported_headline,
    unsupported_tokens,
)
from thoth_control_plane.application.prompt_lab import resolve_style_prompt
from thoth_control_plane.application.prompt_proposal_ports import ProviderInvalidOutput
from thoth_control_plane.assembly.narration_timeline import (
    NARRATION_PREFIX,
    PlacedSfx,
    VoicedBeat,
    narrate_document,
)
from thoth_control_plane.domain.edit_document_v2 import AssetRef, EditDocumentV2
from thoth_control_plane.domain.narration import (
    BEAT_ORDER,
    NarrationMark,
    NarrationPreset,
    NarrationRevoiceInput,
    NarrationScript,
    NarrationScriptInput,
    NarrationStepInput,
    NarrationStepResult,
    NarrationWriteInput,
    SfxEntry,
    TranscriptSegment,
    VoiceRef,
    estimate_voice,
)
from thoth_control_plane.domain.prompts import PROMPT_STARTERS
from thoth_control_plane.domain.story_beats import beat_spans
from thoth_control_plane.domain.style_templates import BUILT_IN_STYLES, StyleTemplate
from thoth_control_plane.voice.loudness import normalize_loudness
from thoth_control_plane.voice.ports import (
    VoiceNotConfigured,
    VoiceRejected,
    VoiceRequest,
    VoiceUnavailable,
)

logger = logging.getLogger(__name__)

#: The same request can be answered differently, so a refused answer is asked for once more.
SCRIPT_ATTEMPTS = 2


@dataclass
class NarrationPorts:
    """What the activities reach; the worker wires the real ones, tests pass fakes."""

    store: Any  # NarrationStore
    studio: Any  # materials(p, d), story_context(p, d) and story_comments(p, d)
    documents: Any  # get_latest(p, d) and write_derived_revision(p, d, base_revision, document)
    main_video: Callable[[str, EditDocumentV2, Path], Awaitable[Path | None]]
    transcribe: Callable[[Path], Awaitable[list[TranscriptSegment]]]
    voice: Callable[[], Any]  # a VoiceSynthesizer; raises VoiceNotConfigured
    upload_audio: Callable[[str, bytes, str], Awaitable[AssetRef]]
    prompts: Any | None  # get_resolved_prompt(p, stage)
    preferences: Any  # get_preference(p, stage)
    provider: Any  # complete_json(provider_id=, model_id=, system=, user=)
    prices: Callable[[], Awaitable[Mapping[tuple[str, str, str], float]]]
    #: Where a title card the main video opens on ends, in seconds; None when there is none.
    intro_card: Callable[[Path], Awaitable[float | None]] | None = None
    #: The workspace asset library: list(workspace) and add_to_project(workspace, project, id).
    library: Any | None = None
    #: The workspace a project belongs to; None when it cannot be told (spec 2026-11-13).
    workspace_of: Callable[[str], Awaitable[str | None]] | None = None


async def workspace_sfx(
    ports: NarrationPorts, project_id: str
) -> tuple[str | None, list[SfxEntry]]:
    """The SFX of the draft's own workspace; none at all when the workspace is unknown.

    There is no fallback to another workspace: a draft never hears another customer's files.
    """
    if ports.library is None or ports.workspace_of is None:
        return None, []
    workspace = await ports.workspace_of(project_id)
    if workspace is None:
        logger.warning("narration has no workspace for its project; no sound effects offered")
        return None, []
    try:
        items = await ports.library.list(workspace)
    except Exception:
        logger.warning("workspace library unavailable; no sound effects offered")
        return workspace, []
    return workspace, [
        SfxEntry(
            sfx_id=item.asset_id,
            file_name=item.name,
            location=item.asset_id,
            checksum=item.checksum,
            duration_seconds=item.duration_seconds or 1.0,
            labels=item.labels
            | {
                "description": item.labels.get("description")
                or item.labels.get("meaning_id")
                or item.name
            },
        )
        for item in items
        if item.kind == "sfx"
    ]


def _style_of(document: Any) -> StyleTemplate | None:
    """The style template a draft took. Only the built-in styles exist until the style editor
    (spec 2026-11-10); an unknown one narrates as before."""
    applied = getattr(document, "style", None)
    return BUILT_IN_STYLES.get(applied.template_id) if applied is not None else None


def _styled_preset(preset: NarrationPreset, style: StyleTemplate) -> NarrationPreset:
    """The project's preset with the style's target length and SFX count, when it sets them."""
    changes: dict[str, Any] = {}
    if style.narration.target_seconds is not None:
        changes["target_seconds"] = style.narration.target_seconds
    if style.narration.max_sfx_cues is not None:
        changes["max_sfx_cues"] = style.narration.max_sfx_cues
    return preset.model_copy(update=changes) if changes else preset


def _roles(materials: Any) -> dict[str, str]:
    return {item.item_id: item.role for item in materials.items if item.role}


class NarrationActivities:
    def __init__(self, ports: NarrationPorts) -> None:
        self._ports = ports

    async def _fail(self, document_id: str, code: str) -> NarrationStepResult:
        await self._ports.store.set_status(document_id, "failed", failure_code=code)
        return NarrationStepResult(code=code)

    @activity.defn(name="narration_mark")
    async def mark(self, mark: NarrationMark) -> None:
        """The workflow's own terminal state: cancelled, or failed after the retries ran out."""
        if mark.workflow_id is not None:
            # A style's undo may have given the row back to the narration it replaced.
            await self._ports.store.close(
                mark.document_id, mark.workflow_id, mark.status, failure_code=mark.failure_code
            )
            return
        await self._ports.store.set_status(
            mark.document_id, mark.status, failure_code=mark.failure_code
        )

    @activity.defn(name="narration_transcribe")
    async def transcribe(self, step: NarrationStepInput) -> NarrationStepResult:
        try:
            self._ports.voice()  # builds the adapter only; no call is made
        except VoiceNotConfigured:
            # Checked first: nothing is transcribed or written before a voice exists.
            return await self._fail(step.document_id, "voice_not_configured")
        scope = await asyncio.to_thread(metering.project_scope, step.project_id)
        with metering.scoped(scope), tempfile.TemporaryDirectory() as work:
            document = await self._ports.documents.get_latest(step.project_id, step.document_id)
            video = await self._ports.main_video(step.project_id, document, Path(work))
            segments = await self._ports.transcribe(video) if video is not None else []
            heard = max((segment.end_seconds for segment in segments), default=0.0)
            if heard > 0:
                await metering.record("transcription", "faster_whisper", heard, "second")
            await self._ports.store.set_transcript(step.document_id, segments)
            await self._ports.store.set_status(step.document_id, "scripting")
        return NarrationStepResult()

    @activity.defn(name="narration_write_script")
    async def write_script(self, step: NarrationScriptInput) -> NarrationStepResult:
        ports = self._ports
        scope = await asyncio.to_thread(metering.project_scope, step.project_id)
        with metering.scoped(scope):
            await ports.store.set_status(step.document_id, "scripting")
            preference = await ports.preferences.get_preference(step.project_id, STAGE)
            if preference is None:
                return await self._fail(step.document_id, "prompt_not_configured")
            preset = await ports.store.get_preset_of(step.document_id)
            document = await ports.documents.get_latest(step.project_id, step.document_id)
            materials = await ports.studio.materials(step.project_id, step.document_id)
            context = await ports.studio.story_context(step.project_id, step.document_id)
            comments = await ports.studio.story_comments(step.project_id, step.document_id)
            # A voice quoting a comment nobody can see reads as made up, so only cards on screen.
            shown = {c.clip_id.removeprefix("clip_") for c in document.clips if not c.hidden}
            facts = facts_from_materials(
                materials, context, [text for item, text in comments.items() if item in shown]
            )
            present = {span.beat for span in beat_spans(document, _roles(materials))}
            beats = [beat for beat in BEAT_ORDER if beat in present] or ["main"]
            transcript = await ports.store.get_transcript(step.document_id)
            _, sfx = await workspace_sfx(ports, step.project_id)
            style = _style_of(document)
            prompt = PROMPT_STARTERS[STAGE].body
            if style is not None:
                # The draft's style speaks in its own voice (spec 2026-11-10, 4).
                prompt = await resolve_style_prompt(ports.prompts, step.project_id, style)
                preset = _styled_preset(preset, style)
            elif ports.prompts is not None:
                try:
                    prompt = (
                        await ports.prompts.get_resolved_prompt(step.project_id, STAGE)
                    ).visible_text
                except Exception:  # no binding saved, or the prompt store is down: the starter
                    prompt = PROMPT_STARTERS[STAGE].body
            card_lines = style is not None and style.narration.card_lines
            card_words = style.narration.card_line_max_words if style is not None else 6
            system, user = build_script_request(
                prompt=prompt,
                beats=beats,  # type: ignore[arg-type]
                facts=facts,
                transcript=transcript,
                preset=preset,
                sfx=sfx,
                note=step.note,
                card_lines=card_lines,
                card_line_max_words=card_words,
            )
            script = None
            for attempt in range(1, SCRIPT_ATTEMPTS + 1):
                try:
                    answer = await ports.provider.complete_json(
                        provider_id=preference.provider_id,
                        model_id=preference.model_id,
                        system=system,
                        user=user,
                    )
                    script = parse_script(
                        answer,
                        beats=beats,
                        preset=preset,
                        sfx_ids={entry.sfx_id for entry in sfx},  # type: ignore[arg-type]
                        card_line_max_words=card_words if card_lines else None,
                    )
                    break
                except (ProviderInvalidOutput, ScriptInvalid) as error:
                    logger.warning("narration script refused attempt=%d: %s", attempt, error)
                except Exception as error:
                    logger.warning("narration script call failed: %s", type(error).__name__)
                    return await self._fail(step.document_id, _safe_failure_code(error))
            if script is None:
                return await self._fail(step.document_id, "invalid_provider_output")
            # A headline nobody reviews shows only when the facts hold it (2026-11-12).
            script = supported_headline(script, facts, transcript)
            estimate = estimate_voice(script, preset, await ports.prices())
            # A styled draft's cut preview skips the title card the voice will skip.
            intro = await self._intro_frames(step, document) if style is not None else None
            await ports.store.set_script(
                step.document_id,
                script,
                estimate,
                unsupported_tokens(script, facts, transcript),
                intro_frames=intro,
            )
        return NarrationStepResult()

    async def _voice_beats(
        self,
        project_id: str,
        script: NarrationScript,
        preset: NarrationPreset,
        beats: set[str],
        on_voice: Callable[[VoiceRef], Awaitable[None]],
    ) -> None:
        """Voice the named beats, handing each voice over as soon as it exists, so a retry
        after a failure never pays for a beat twice (ElevenLabs bills per call)."""
        synthesizer = self._ports.voice()
        # Request IDs stitch only beats voiced in this call: IDs must be under two hours old.
        stitched: list[str] = []
        for index, beat in enumerate(script.beats):
            if beat.beat not in beats:
                continue
            result = await synthesizer.synthesize(
                VoiceRequest(
                    text=beat.text,
                    language=preset.language,
                    voice_id=preset.voice_id,
                    model=preset.voice_model,
                    previous_text=script.beats[index - 1].text if index > 0 else None,
                    next_text=script.beats[index + 1].text
                    if index + 1 < len(script.beats)
                    else None,
                    previous_request_ids=stitched[-3:] or None,
                )
            )
            if result.request_id:
                stitched.append(result.request_id)
            # One level for every beat: the voices ran 4 dB apart and sat low (2026-11-12).
            audio = await asyncio.to_thread(normalize_loudness, result.audio, result.media_type)
            asset = await self._ports.upload_audio(project_id, audio, result.media_type)
            await on_voice(
                VoiceRef(
                    beat=beat.beat,
                    asset=asset,
                    duration_seconds=max(result.duration_seconds, 0.05),
                    words=result.word_timings or [],
                )
            )

    @activity.defn(name="narration_voice")
    async def voice(self, step: NarrationStepInput) -> NarrationStepResult:
        ports = self._ports
        scope = await asyncio.to_thread(metering.project_scope, step.project_id)
        with metering.scoped(scope):
            await ports.store.set_status(step.document_id, "voicing")
            script = await ports.store.get_script(step.document_id)
            preset = await ports.store.get_preset_of(step.document_id)
            # A retry resumes: the voices an earlier attempt stored are kept, not bought again.
            voices = await ports.store.get_voices(step.document_id)
            done = {voice.beat for voice in voices}

            async def keep(voice: VoiceRef) -> None:
                voices.append(voice)
                voices.sort(key=lambda item: BEAT_ORDER.index(item.beat))
                await ports.store.set_voices(step.document_id, voices)

            try:
                await self._voice_beats(
                    step.project_id,
                    script,
                    preset,
                    {beat.beat for beat in script.beats} - done,
                    keep,
                )
            except VoiceNotConfigured:
                return await self._fail(step.document_id, "voice_not_configured")
            except VoiceRejected:
                return await self._fail(step.document_id, "voice_rejected")
            except VoiceUnavailable:
                raise  # retryable: the provider was unreachable or answered oddly
        return NarrationStepResult()

    async def _intro_frames(self, step: NarrationStepInput, document: EditDocumentV2) -> int:
        """Frames of the main video's opening title card, read on the first narration only: a
        re-voice keeps where the operator left the main video. Never fails the draft."""
        check = self._ports.intro_card
        if check is None or any(c.clip_id.startswith(NARRATION_PREFIX) for c in document.clips):
            return 0
        try:
            with tempfile.TemporaryDirectory() as work:
                video = await self._ports.main_video(step.project_id, document, Path(work))
                seconds = await check(video) if video is not None else None
        except Exception as error:
            logger.warning("title card check failed error=%s", type(error).__name__)
            return 0
        if seconds is None:
            return 0
        logger.info("narration starts after a title card seconds=%.3f", seconds)
        # Up, never down: the card's last frame may lie just before the first read without it.
        return math.ceil(seconds * document.canvas.fps)

    async def _write(
        self, step: NarrationStepInput, voices: list[VoiceRef], *, place_sfx: bool
    ) -> None:
        ports = self._ports
        script = await ports.store.get_script(step.document_id)
        preset = await ports.store.get_preset_of(step.document_id)
        document = await ports.documents.get_latest(step.project_id, step.document_id)
        materials = await ports.studio.materials(step.project_id, step.document_id)
        cues = script.sfx_cues if script and place_sfx else []
        workspace, entries = await workspace_sfx(ports, step.project_id) if cues else (None, [])
        library = {entry.sfx_id: entry for entry in entries}
        placed = []
        for cue in cues:
            entry = library.get(cue.sfx_id)
            if entry is None or workspace is None:
                continue
            copied = await ports.library.add_to_project(workspace, step.project_id, cue.sfx_id)
            placed.append(
                PlacedSfx(
                    cue=cue, asset=copied.to_asset_ref(), duration_seconds=entry.duration_seconds
                )
            )
        stored = await ports.store.get_intro_frames(step.document_id)
        intro = stored if stored is not None else await self._intro_frames(step, document)
        style = _style_of(document)
        cards = (
            {beat.beat: beat.card_line for beat in script.beats if beat.card_line} if script else {}
        )
        narrated = narrate_document(
            document,
            [
                VoicedBeat(
                    beat=voice.beat,
                    asset=voice.asset,
                    duration_seconds=voice.duration_seconds,
                    words=voice.words,
                )
                for voice in voices
            ],
            placed,
            preset,
            _roles(materials),
            place_sfx=place_sfx,
            intro_frames=intro,
            style=style,
            card_lines=cards,
            headline=script.headline if script else None,
        )
        await ports.documents.write_derived_revision(
            step.project_id, step.document_id, document.revision, narrated
        )

    @activity.defn(name="narration_write_draft")
    async def write_draft(self, step: NarrationWriteInput) -> NarrationStepResult:
        scope = await asyncio.to_thread(metering.project_scope, step.project_id)
        with metering.scoped(scope):
            await self._ports.store.set_status(step.document_id, "writing")
            await self._write(
                step,
                await self._ports.store.get_voices(step.document_id),
                place_sfx=step.place_sfx,
            )
            await self._ports.store.set_status(step.document_id, "completed")
        return NarrationStepResult()

    @activity.defn(name="narration_revoice")
    async def revoice(self, step: NarrationRevoiceInput) -> NarrationStepResult:
        """Voice one edited beat again and store it; the workflow's write step then rewrites
        the draft, so a write that is retried never pays for the voice again."""
        ports = self._ports
        scope = await asyncio.to_thread(metering.project_scope, step.project_id)
        with metering.scoped(scope):
            script = await ports.store.get_script(step.document_id)
            preset = await ports.store.get_preset_of(step.document_id)
            voices = [
                voice
                for voice in await ports.store.get_voices(step.document_id)
                if voice.beat != step.beat
            ]

            async def keep(voice: VoiceRef) -> None:
                voices.append(voice)
                voices.sort(key=lambda item: BEAT_ORDER.index(item.beat))
                await ports.store.set_voices(step.document_id, voices)

            try:
                await self._voice_beats(step.project_id, script, preset, {step.beat}, keep)
            except VoiceNotConfigured:
                return NarrationStepResult(code="voice_not_configured")
            except VoiceRejected:
                return NarrationStepResult(code="voice_rejected")
            await ports.store.clear_stale(step.document_id, step.beat)
        return NarrationStepResult()


def build_narration_activities(settings: Any, media: Any) -> NarrationActivities:
    """The production ports, on the worker's editor database and media store."""
    import functools

    from thoth_control_plane.application.edit_documents import EditDocumentService
    from thoth_control_plane.application.editor_asset_uploads import EditorAssetUploadService
    from thoth_control_plane.application.prompt_lab import PromptLabService
    from thoth_control_plane.application.sfx_library import SfxAssets
    from thoth_control_plane.application.studio_imports import StudioImportService
    from thoth_control_plane.application.workflow_studio_imports import (
        WorkflowStudioImportService,
    )
    from thoth_control_plane.application.workspace_library import WorkspaceLibraryService
    from thoth_control_plane.attribution.adapters.speech import WhisperTranscriber
    from thoth_control_plane.infrastructure.artifact_root import LocalArtifactRoot
    from thoth_control_plane.infrastructure.editor_asset_repository import (
        PostgresEditorAssetRepository,
    )
    from thoth_control_plane.infrastructure.editor_repository import (
        PostgresEditDocumentRepository,
    )
    from thoth_control_plane.infrastructure.media_probe import probe_media
    from thoth_control_plane.infrastructure.narration_store import NarrationStore
    from thoth_control_plane.infrastructure.prompt_proposal_repository import (
        PostgresPromptProposalRepository,
    )
    from thoth_control_plane.infrastructure.prompt_provider import OpenAICompatiblePromptProvider
    from thoth_control_plane.infrastructure.prompt_repository import PostgresPromptLabRepository
    from thoth_control_plane.infrastructure.report_store import ReportStore
    from thoth_control_plane.infrastructure.studio_import_repository import (
        PostgresStudioImportRepository,
    )
    from thoth_control_plane.infrastructure.usage_store import UsageStore
    from thoth_control_plane.infrastructure.workflow_run_store import WorkflowRunStore
    from thoth_control_plane.infrastructure.workspace_asset_repository import (
        PostgresWorkspaceAssetRepository,
    )
    from thoth_control_plane.voice.factory import build_voice

    database = settings.THOTH_EDITOR_DATABASE_URL.get_secret_value()
    probe = functools.partial(probe_media, settings.THOTH_FFPROBE)
    assets = PostgresEditorAssetRepository(database)
    studio = WorkflowStudioImportService(
        runs=WorkflowRunStore.connect(database),
        reports=ReportStore.connect(database),
        media=media,
        assets=assets,
        imports=StudioImportService(PostgresStudioImportRepository(database)),
        probe=probe,
    )
    uploads = EditorAssetUploadService(
        assets, LocalArtifactRoot(settings.THOTH_CONTROL_PLANE_ARTIFACT_ROOT, media), probe
    )
    transcriber = WhisperTranscriber(settings.THOTH_WHISPER_MODEL_DIR)
    usage = UsageStore.connect(database)

    async def upload_audio(project_id: str, audio: bytes, media_type: str) -> AssetRef:
        async def chunks():  # type: ignore[no-untyped-def]
            yield audio

        return (await uploads.upload(project_id, media_type, chunks())).to_asset_ref()

    async def main_video(project_id: str, document: EditDocumentV2, directory: Path) -> Path | None:
        main_tracks = {track.track_id for track in document.tracks if track.kind == "main_video"}
        clip = next(
            (
                c
                for c in document.clips
                if c.track_id in main_tracks and getattr(c, "asset_id", None)
            ),
            None,
        )
        if clip is None:
            return None
        record = await assets.get_ready_record(project_id=project_id, asset_id=clip.asset_id)  # type: ignore[union-attr]
        if record is None:
            return None
        target = directory / f"main{Path(record.artifact_location).suffix}"
        await asyncio.to_thread(media.fetch, record.artifact_location, target)
        return target

    async def transcribe(video: Path) -> list[TranscriptSegment]:
        # ponytail: the first 15 minutes; a longer main video is not a short-form source.
        heard = await transcriber.transcribe(video, seconds=900.0)
        return [
            TranscriptSegment(text=s.text, start_seconds=s.start, end_seconds=s.end)
            for s in heard.segments
        ]

    async def prices() -> dict[tuple[str, str, str], float]:
        rows = await asyncio.to_thread(usage.prices)
        return {(row.kind, row.key, row.unit): row.usd_per_unit for row in rows}

    async def workspace_of(project_id: str) -> str | None:
        try:
            return await asyncio.to_thread(usage.workspace_of_project, project_id)
        except Exception:
            logger.warning("project workspace lookup unavailable")
            return None

    async def intro_card(video: Path) -> float | None:
        # The assembly activity's local readers: no provider, nothing written.
        from thoth_control_plane.assembly.intro_card import intro_card_end
        from thoth_control_plane.attribution.adapters.frames import FfmpegFrameSource
        from thoth_control_plane.attribution.adapters.ocr import RapidOcrReader

        return await intro_card_end(
            video, FfmpegFrameSource(settings.THOTH_FFMPEG), RapidOcrReader(angle=False)
        )

    return NarrationActivities(
        NarrationPorts(
            store=NarrationStore(database),
            studio=studio,
            documents=EditDocumentService(PostgresEditDocumentRepository(database)),
            main_video=main_video,
            transcribe=transcribe,
            voice=lambda: build_voice(settings, "elevenlabs"),
            upload_audio=upload_audio,
            prompts=PromptLabService(PostgresPromptLabRepository(database)),
            preferences=PostgresPromptProposalRepository(database),
            provider=OpenAICompatiblePromptProvider(
                runtime_catalog=settings.THOTH_PROMPT_PROVIDER_CATALOG,
                secrets=settings.prompt_provider_secrets,
            ),
            prices=prices,
            intro_card=intro_card,
            library=WorkspaceLibraryService(
                PostgresWorkspaceAssetRepository(database),
                None,
                probe,
                media,
                SfxAssets(assets=assets, media=media, probe=probe),
                Path(settings.THOTH_FFMPEG),
            ),
            workspace_of=workspace_of,
        )
    )
