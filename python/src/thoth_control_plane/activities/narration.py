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
    NarrationPreset,
    NarrationRevoiceInput,
    NarrationScript,
    NarrationScriptInput,
    NarrationStepInput,
    NarrationStepResult,
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

    @activity.defn(name="narration_transcribe")
    async def transcribe(self, step: NarrationStepInput) -> NarrationStepResult:
        scope = await asyncio.to_thread(metering.project_scope, step.project_id)
        with metering.scoped(scope), tempfile.TemporaryDirectory() as work:
            document = await self._ports.documents.get_latest(step.project_id, step.document_id)
            video = await self._ports.main_video(step.project_id, document, Path(work))
            segments = await self._ports.transcribe(video) if video is not None else []
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
        only: str | None = None,
    ) -> list[VoiceRef]:
        synthesizer = self._ports.voice()
        voices = []
        for index, beat in enumerate(script.beats):
            if only is not None and beat.beat != only:
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
                )
            )
            asset = await self._ports.upload_audio(project_id, result.audio, result.media_type)
            voices.append(
                VoiceRef(
                    beat=beat.beat,
                    asset=asset,
                    duration_seconds=max(result.duration_seconds, 0.05),
                    words=result.word_timings or [],
                )
            )
        return voices

    @activity.defn(name="narration_voice")
    async def voice(self, step: NarrationStepInput) -> NarrationStepResult:
        ports = self._ports
        scope = await asyncio.to_thread(metering.project_scope, step.project_id)
        with metering.scoped(scope):
            await ports.store.set_status(step.document_id, "voicing")
            script = await ports.store.get_script(step.document_id)
            preset = await ports.store.get_preset_of(step.document_id)
            try:
                voices = await self._voice_beats(step.project_id, script, preset)
            except VoiceNotConfigured:
                return await self._fail(step.document_id, "voice_not_configured")
            except VoiceRejected:
                return await self._fail(step.document_id, "voice_rejected")
            except VoiceUnavailable:
                raise  # retryable: the provider was unreachable or answered oddly
            await ports.store.set_voices(step.document_id, voices)
        return NarrationStepResult()

    async def _write(self, step: NarrationStepInput, voices: list[VoiceRef]) -> None:
        ports = self._ports
        script = await ports.store.get_script(step.document_id)
        preset = await ports.store.get_preset_of(step.document_id)
        document = await ports.documents.get_latest(step.project_id, step.document_id)
        materials = await ports.studio.materials(step.project_id, step.document_id)
        library = {entry.sfx_id: entry for entry in await ports.store.list_sfx()}
        placed = []
        for cue in script.sfx_cues if script else []:
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
        )
        await ports.documents.write_derived_revision(
            step.project_id, step.document_id, document.revision, narrated
        )

    @activity.defn(name="narration_write_draft")
    async def write_draft(self, step: NarrationStepInput) -> NarrationStepResult:
        scope = await asyncio.to_thread(metering.project_scope, step.project_id)
        with metering.scoped(scope):
            await self._ports.store.set_status(step.document_id, "writing")
            await self._write(step, await self._ports.store.get_voices(step.document_id))
            await self._ports.store.set_status(step.document_id, "completed")
        return NarrationStepResult()

    @activity.defn(name="narration_revoice")
    async def revoice(self, step: NarrationRevoiceInput) -> NarrationStepResult:
        """Voice one beat again after an edit, then rewrite the draft around it."""
        ports = self._ports
        scope = await asyncio.to_thread(metering.project_scope, step.project_id)
        with metering.scoped(scope):
            script = await ports.store.get_script(step.document_id)
            preset = await ports.store.get_preset_of(step.document_id)
            try:
                fresh = await self._voice_beats(step.project_id, script, preset, only=step.beat)
            except (VoiceNotConfigured, VoiceRejected) as error:
                code = (
                    "voice_not_configured"
                    if isinstance(error, VoiceNotConfigured)
                    else "voice_rejected"
                )
                return NarrationStepResult(code=code)
            voices = [
                voice
                for voice in await ports.store.get_voices(step.document_id)
                if voice.beat != step.beat
            ] + fresh
            voices.sort(key=lambda voice: BEAT_ORDER.index(voice.beat))
            await self._write(step, voices)
            await ports.store.set_voices(step.document_id, voices)
            await ports.store.clear_stale(step.document_id, step.beat)
        return NarrationStepResult()
