"""The narration activities with fakes: no voice before approval, safe failure codes (Task 7)."""

from __future__ import annotations

import asyncio
import json
import logging
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from thoth_control_plane.activities.narration import NarrationActivities, NarrationPorts
from thoth_control_plane.domain.edit_document_v2 import AssetRef, EditDocumentV2
from thoth_control_plane.domain.narration import (
    NarrationPreset,
    NarrationRevoiceInput,
    NarrationScriptInput,
    NarrationStepInput,
    SfxEntry,
    TranscriptSegment,
)
from thoth_control_plane.domain.studio_imports import StudioMaterial, StudioMaterials
from thoth_control_plane.voice.ports import SynthesizedVoice, VoiceNotConfigured, WordTiming

CASES = json.loads(
    (Path(__file__).parents[3] / "dashboard/src/features/studio/story_beat_cases.json").read_text(
        "utf-8"
    )
)
STEP = NarrationStepInput(project_id="project_001", document_id="edoc_abc123")
SECRET = "sk-elevenlabs-should-never-appear"


class Store:
    def __init__(self) -> None:
        self.status: list[tuple[str, str | None]] = []
        self.transcript: list[TranscriptSegment] = []
        self.script: Any = None
        self.estimate: Any = None
        self.unsupported: Any = None
        self.voices: list[Any] = []
        self.cleared: list[str] = []

    async def set_status(self, _doc: str, status: str, *, failure_code: str | None = None) -> None:
        self.status.append((status, failure_code))

    async def set_transcript(self, _doc: str, segments: list[TranscriptSegment]) -> None:
        self.transcript = segments

    async def get_transcript(self, _doc: str) -> list[TranscriptSegment]:
        return self.transcript

    async def get_preset_of(self, _doc: str) -> NarrationPreset:
        return NarrationPreset()

    async def list_sfx(self) -> list[SfxEntry]:
        return [
            SfxEntry(
                sfx_id="whoosh",
                file_name="whoosh.mp3",
                location="sfx/a.mp3",
                checksum="sha256:" + "a" * 64,
                duration_seconds=1.0,
                labels={"description": "swipe"},
            )
        ]

    async def set_script(self, _doc: str, script: Any, estimate: Any, unsupported: Any) -> None:
        self.status.append(("awaiting_approval", None))
        self.script, self.estimate, self.unsupported = script, estimate, unsupported

    async def get_script(self, _doc: str) -> Any:
        return self.script

    async def set_voices(self, _doc: str, voices: list[Any]) -> None:
        self.voices = voices

    async def get_voices(self, _doc: str) -> list[Any]:
        return self.voices

    async def clear_stale(self, _doc: str, beat: str) -> None:
        self.cleared.append(beat)


class Documents:
    def __init__(self) -> None:
        self.document = EditDocumentV2.model_validate(deepcopy(CASES["cases"][0]["document"]))
        self.written: list[EditDocumentV2] = []

    async def get_latest(self, _p: str, _d: str) -> EditDocumentV2:
        return self.written[-1] if self.written else self.document

    async def write_derived_revision(self, _p: str, _d: str, base: int, document: Any) -> None:
        assert base == (await self.get_latest(_p, _d)).revision
        self.written.append(document.model_copy(update={"revision": base + 1}))


class Studio:
    async def materials(self, _p: str, _d: str) -> StudioMaterials:
        return StudioMaterials(
            document_id="edoc_abc123",
            provenance_available=True,
            items=[
                StudioMaterial(
                    item_id="main",
                    role="main",
                    label="Main",
                    media_kind="video",
                    disposition="attached",
                    owner_handle="kucing.id",
                    platform="tiktok",
                ),
                StudioMaterial(
                    item_id="comment_card_001",
                    role="comment_card",
                    label="lucu",
                    media_kind="image",
                    disposition="attached",
                ),
            ],
        )

    async def story_context(self, _p: str, _d: str) -> tuple[str, str]:
        return ("Kucing viral", "Kucing mencuri ikan")


class Voice:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    async def synthesize(self, request: Any) -> SynthesizedVoice:
        self.requests.append(request)
        words = [
            WordTiming(text=word, start_seconds=i * 0.4, end_seconds=i * 0.4 + 0.3)
            for i, word in enumerate(request.text.split())
        ]
        return SynthesizedVoice(
            audio=b"MP3",
            media_type="audio/mpeg",
            duration_seconds=max(words[-1].end_seconds, 0.5),
            word_timings=words,
        )


def ports(**overrides: Any) -> tuple[NarrationPorts, dict[str, Any]]:
    seen: dict[str, Any] = {
        "store": Store(),
        "documents": Documents(),
        "voice": Voice(),
        "provider_calls": 0,
        "uploads": 0,
    }

    async def main_video(_p: str, _doc: Any, directory: Path) -> Path:
        path = directory / "main.mp4"
        path.write_bytes(b"x")
        return path

    async def transcribe(_path: Path) -> list[TranscriptSegment]:
        return [TranscriptSegment(text="kucing itu lari", start_seconds=0.0, end_seconds=1.0)]

    async def upload_audio(project: str, _audio: bytes, _media: str) -> AssetRef:
        seen["uploads"] += 1
        return AssetRef(
            asset_id=f"asset_voice_{seen['uploads']}",
            project_id=project,
            kind="audio",
            duration_in_frames=60,
            has_audio=True,
            validation_state="ready",
        )

    class Provider:
        async def complete_json(self, **_: Any) -> dict[str, Any]:
            seen["provider_calls"] += 1
            return overrides.get("answer") or {
                "beats": [
                    {"beat": "hook", "text": "Kucing ini bikin heboh."},
                    {"beat": "main", "text": "Ikan diambil dalam sekejap."},
                    {"beat": "reactions", "text": "Warganet tertawa, kata Andi."},
                ],
                "sfx_cues": [{"sfx_id": "whoosh", "beat": "reactions", "moment": "comment_appear"}],
            }

    class Preferences:
        async def get_preference(self, _p: str, _s: str) -> Any:
            return overrides.get(
                "preference", SimpleNamespace(provider_id="openrouter", model_id="m")
            )

    class SfxAssets:
        async def ensure_project_sfx(self, project: str, entry: SfxEntry) -> AssetRef:
            return AssetRef(
                asset_id="asset_sfx",
                project_id=project,
                kind="audio",
                duration_in_frames=30,
                has_audio=True,
                validation_state="ready",
            )

    def voice() -> Voice:
        if overrides.get("voice_missing"):
            raise VoiceNotConfigured(f"elevenlabs {SECRET}"[:0] + "elevenlabs")
        return seen["voice"]

    async def prices() -> dict[tuple[str, str, str], float]:
        return {}

    built = NarrationPorts(
        store=seen["store"],
        studio=Studio(),
        documents=seen["documents"],
        main_video=main_video,
        transcribe=transcribe,
        voice=voice,
        upload_audio=upload_audio,
        sfx_assets=SfxAssets(),
        prompts=None,
        preferences=Preferences(),
        provider=Provider(),
        prices=prices,
    )
    return built, seen


@pytest.fixture(autouse=True)
def no_meter_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    from thoth_control_plane import metering

    monkeypatch.setattr(metering, "project_scope", lambda _project: None)


def run(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


def test_transcribing_and_scripting_never_voice_anything() -> None:
    built, seen = ports()
    activities = NarrationActivities(built)

    run(activities.transcribe(STEP))
    result = run(activities.write_script(NarrationScriptInput(**STEP.model_dump())))

    assert result.code is None
    assert seen["voice"].requests == [] and seen["uploads"] == 0 and seen["provider_calls"] == 1
    store = seen["store"]
    assert [beat.beat for beat in store.script.beats] == ["hook", "main", "reactions"]
    assert store.estimate.characters == sum(len(beat.text) for beat in store.script.beats)
    assert store.unsupported == {"reactions": ["Andi"]}
    assert store.status[-1] == ("awaiting_approval", None)
    assert store.transcript[0].text == "kucing itu lari"


def test_no_script_model_fails_before_any_provider_call() -> None:
    built, seen = ports(preference=None)

    result = run(NarrationActivities(built).write_script(NarrationScriptInput(**STEP.model_dump())))

    assert result.code == "prompt_not_configured" and seen["provider_calls"] == 0
    assert seen["store"].status[-1] == ("failed", "prompt_not_configured")


def test_an_unusable_answer_fails_as_invalid_provider_output() -> None:
    built, seen = ports(answer={"beats": [{"beat": "outro", "text": "x"}]})

    result = run(NarrationActivities(built).write_script(NarrationScriptInput(**STEP.model_dump())))

    assert result.code == "invalid_provider_output"
    assert seen["store"].status[-1] == ("failed", "invalid_provider_output")


def test_voicing_stitches_neighbours_and_writing_narrates_the_draft() -> None:
    built, seen = ports()
    activities = NarrationActivities(built)
    run(activities.write_script(NarrationScriptInput(**STEP.model_dump())))

    run(activities.voice(STEP))
    run(activities.write_draft(STEP))

    requests = seen["voice"].requests
    assert [request.previous_text for request in requests] == [
        None,
        "Kucing ini bikin heboh.",
        "Ikan diambil dalam sekejap.",
    ]
    assert requests[0].next_text == "Ikan diambil dalam sekejap."
    written = seen["documents"].written[-1]
    assert {
        "clip_narration_hook",
        "clip_narration_main",
        "clip_narration_reactions",
        "clip_sfx_0",
    } <= {clip.clip_id for clip in written.clips}
    assert seen["store"].status[-1] == ("completed", None)


def test_a_missing_voice_key_fails_safely_and_leaves_the_draft(
    caplog: pytest.LogCaptureFixture,
) -> None:
    built, seen = ports(voice_missing=True)
    activities = NarrationActivities(built)
    run(activities.write_script(NarrationScriptInput(**STEP.model_dump())))

    with caplog.at_level(logging.DEBUG):
        result = run(activities.voice(STEP))

    assert result.code == "voice_not_configured"
    assert seen["documents"].written == [] and seen["uploads"] == 0
    assert SECRET not in caplog.text


def test_re_voicing_one_beat_voices_only_that_beat_and_clears_it() -> None:
    built, seen = ports()
    activities = NarrationActivities(built)
    run(activities.write_script(NarrationScriptInput(**STEP.model_dump())))
    run(activities.voice(STEP))
    run(activities.write_draft(STEP))
    before = len(seen["voice"].requests)

    run(activities.revoice(NarrationRevoiceInput(**STEP.model_dump(), beat="main")))

    assert len(seen["voice"].requests) == before + 1
    assert seen["voice"].requests[-1].text == "Ikan diambil dalam sekejap."
    assert seen["store"].cleared == ["main"]
    assert len(seen["documents"].written) == 1  # the workflow's write step writes the draft


def test_a_missing_voice_key_stops_the_narration_before_any_spend() -> None:
    """The API holds no provider key, so the worker checks it first (Task 9 ruling)."""
    built, seen = ports(voice_missing=True)

    result = run(NarrationActivities(built).transcribe(STEP))

    assert result.code == "voice_not_configured"
    assert seen["store"].status == [("failed", "voice_not_configured")]
    assert seen["store"].transcript == [] and seen["provider_calls"] == 0


def test_a_retried_voice_step_never_voices_a_beat_twice() -> None:
    """ElevenLabs bills per call: a retry after beat 2 failed resumes at beat 2 (review I3)."""
    from thoth_control_plane.voice.ports import VoiceUnavailable

    built, seen = ports()
    activities = NarrationActivities(built)
    run(activities.write_script(NarrationScriptInput(**STEP.model_dump())))
    voice = seen["voice"]
    real = voice.synthesize
    failed = {"once": False}

    async def flaky(request):  # type: ignore[no-untyped-def]
        if len(voice.requests) == 1 and not failed["once"]:
            failed["once"] = True
            raise VoiceUnavailable("elevenlabs_unreachable")
        return await real(request)

    voice.synthesize = flaky
    with pytest.raises(VoiceUnavailable):
        run(activities.voice(STEP))
    run(activities.voice(STEP))

    texts = [request.text for request in voice.requests]
    assert texts == [
        "Kucing ini bikin heboh.",
        "Ikan diambil dalam sekejap.",
        "Warganet tertawa, kata Andi.",
    ]
    assert [ref.beat for ref in seen["store"].voices] == ["hook", "main", "reactions"]


def test_a_re_voice_replaces_one_stored_voice_without_writing_the_draft() -> None:
    built, seen = ports()
    activities = NarrationActivities(built)
    run(activities.write_script(NarrationScriptInput(**STEP.model_dump())))
    run(activities.voice(STEP))
    before = {ref.beat: ref.asset.asset_id for ref in seen["store"].voices}

    run(activities.revoice(NarrationRevoiceInput(**STEP.model_dump(), beat="main")))

    after = {ref.beat: ref.asset.asset_id for ref in seen["store"].voices}
    assert after["hook"] == before["hook"] and after["main"] != before["main"]
    assert seen["documents"].written == [] and seen["store"].cleared == ["main"]
