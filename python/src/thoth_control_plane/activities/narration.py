"""The narration activities: transcribe, write the script, voice it, write the draft (spec 5).

Each step records its state on the draft's narration row, so Studio shows where it is. Known
failures are recorded as a safe code and returned; anything else is raised for Temporal's retry.
Nothing here voices a beat before the workflow has the operator's approval: the workflow only
calls `narration_voice` after it.
"""

from __future__ import annotations

import asyncio
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
    unsupported_tokens,
)
from thoth_control_plane.assembly.narration_timeline import (
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
    TranscriptSegment,
    VoiceRef,
    estimate_voice,
)
from thoth_control_plane.domain.prompts import PROMPT_STARTERS
from thoth_control_plane.domain.story_beats import beat_spans
from thoth_control_plane.voice.ports import (
    VoiceNotConfigured,
    VoiceRejected,
    VoiceRequest,
    VoiceUnavailable,
)


@dataclass
class NarrationPorts:
    """What the activities reach; the worker wires the real ones, tests pass fakes."""

    store: Any  # NarrationStore
    studio: Any  # materials(p, d) and story_context(p, d)
    documents: Any  # get_latest(p, d) and write_derived_revision(p, d, base_revision, document)
    main_video: Callable[[str, EditDocumentV2, Path], Awaitable[Path | None]]
    transcribe: Callable[[Path], Awaitable[list[TranscriptSegment]]]
    voice: Callable[[], Any]  # a VoiceSynthesizer; raises VoiceNotConfigured
    upload_audio: Callable[[str, bytes, str], Awaitable[AssetRef]]
    sfx_assets: Any  # ensure_project_sfx(project_id, entry)
    prompts: Any | None  # get_resolved_prompt(p, stage)
    preferences: Any  # get_preference(p, stage)
    provider: Any  # complete_json(provider_id=, model_id=, system=, user=)
    prices: Callable[[], Awaitable[Mapping[tuple[str, str, str], float]]]


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
            facts = facts_from_materials(materials, context)
            present = {span.beat for span in beat_spans(document, _roles(materials))}
            beats = [beat for beat in BEAT_ORDER if beat in present] or ["main"]
            transcript = await ports.store.get_transcript(step.document_id)
            sfx = await ports.store.list_sfx()
            prompt = PROMPT_STARTERS[STAGE].body
            if ports.prompts is not None:
                try:
                    prompt = (
                        await ports.prompts.get_resolved_prompt(step.project_id, STAGE)
                    ).visible_text
                except Exception:  # no binding saved, or the prompt store is down: the starter
                    prompt = PROMPT_STARTERS[STAGE].body
            system, user = build_script_request(
                prompt=prompt,
                beats=beats,  # type: ignore[arg-type]
                facts=facts,
                transcript=transcript,
                preset=preset,
                sfx=sfx,
                note=step.note,
            )
            try:
                answer = await ports.provider.complete_json(
                    provider_id=preference.provider_id,
                    model_id=preference.model_id,
                    system=system,
                    user=user,
                )
            except Exception as error:
                return await self._fail(step.document_id, _safe_failure_code(error))
            try:
                script = parse_script(
                    answer,
                    beats=beats,
                    preset=preset,
                    sfx_ids={entry.sfx_id for entry in sfx},  # type: ignore[arg-type]
                )
            except ScriptInvalid:
                return await self._fail(step.document_id, "invalid_provider_output")
            estimate = estimate_voice(script, preset, await ports.prices())
            await ports.store.set_script(
                step.document_id, script, estimate, unsupported_tokens(script, facts, transcript)
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
            asset = await self._ports.upload_audio(project_id, result.audio, result.media_type)
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

    async def _write(
        self, step: NarrationStepInput, voices: list[VoiceRef], *, place_sfx: bool
    ) -> None:
        ports = self._ports
        script = await ports.store.get_script(step.document_id)
        preset = await ports.store.get_preset_of(step.document_id)
        document = await ports.documents.get_latest(step.project_id, step.document_id)
        materials = await ports.studio.materials(step.project_id, step.document_id)
        library = {entry.sfx_id: entry for entry in await ports.store.list_sfx()}
        placed = []
        for cue in script.sfx_cues if script and place_sfx else []:
            entry = library.get(cue.sfx_id)
            if entry is None:
                continue
            asset = await ports.sfx_assets.ensure_project_sfx(step.project_id, entry)
            placed.append(PlacedSfx(cue=cue, asset=asset, duration_seconds=entry.duration_seconds))
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

    return NarrationActivities(
        NarrationPorts(
            store=NarrationStore(database),
            studio=studio,
            documents=EditDocumentService(PostgresEditDocumentRepository(database)),
            main_video=main_video,
            transcribe=transcribe,
            voice=lambda: build_voice(settings, "elevenlabs"),
            upload_audio=upload_audio,
            sfx_assets=SfxAssets(assets=assets, media=media, probe=probe),
            prompts=PromptLabService(PostgresPromptLabRepository(database)),
            preferences=PostgresPromptProposalRepository(database),
            provider=OpenAICompatiblePromptProvider(
                runtime_catalog=settings.THOTH_PROMPT_PROVIDER_CATALOG,
                secrets=settings.prompt_provider_secrets,
            ),
            prices=prices,
        )
    )
