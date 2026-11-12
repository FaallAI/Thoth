"""The narration activities with fakes: no voice before approval, safe failure codes (Task 7)."""

from __future__ import annotations

import asyncio
import json
import logging
import math
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from thoth_control_plane.activities.narration import NarrationActivities, NarrationPorts
from thoth_control_plane.application.prompt_proposal_ports import (
    ProviderInvalidOutput,
    ProviderUnavailable,
)
from thoth_control_plane.domain.edit_document_v2 import AssetRef, EditDocumentV2
from thoth_control_plane.domain.editor_assets import EditorAsset
from thoth_control_plane.domain.narration import (
    NarrationPreset,
    NarrationRevoiceInput,
    NarrationScriptInput,
    NarrationStepInput,
    NarrationWriteInput,
    TranscriptSegment,
)
from thoth_control_plane.domain.studio_imports import StudioMaterial, StudioMaterials
from thoth_control_plane.domain.workspace_assets import WorkspaceAsset
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

    async def set_script(
        self,
        _doc: str,
        script: Any,
        estimate: Any,
        unsupported: Any,
        *,
        intro_frames: int | None = None,
    ) -> None:
        self.status.append(("awaiting_approval", None))
        self.script, self.estimate, self.unsupported = script, estimate, unsupported
        self.intro_frames = intro_frames

    async def get_intro_frames(self, _doc: str) -> int | None:
        return getattr(self, "intro_frames", None)

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
                    label="@andi",
                    media_kind="image",
                    disposition="attached",
                ),
            ],
        )

    async def story_context(self, _p: str, _d: str) -> tuple[str, str]:
        return ("Kucing viral", "Kucing mencuri ikan")

    async def story_comments(self, _p: str, _d: str) -> dict[str, str]:
        return {
            "comment_card_001": "lucu sekali",
            "comment_card_009": "kartunya tidak tampil",
            "comment_000": "tanpa kartu",
        }


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


GOOD_ANSWER = {
    "beats": [
        {"beat": "hook", "text": "Kucing ini bikin heboh."},
        {"beat": "main", "text": "Ikan diambil dalam sekejap."},
        {"beat": "reactions", "text": "Warganet tertawa, kata Andi."},
    ],
    "sfx_cues": [{"sfx_id": "lib_whoosh", "beat": "reactions", "moment": "comment_appear"}],
}


def library_item(asset_id: str, description: str) -> WorkspaceAsset:
    return WorkspaceAsset(
        asset_id=asset_id,
        workspace_id="ws",
        kind="sfx",
        name=asset_id.removeprefix("lib_"),
        labels={"description": description},
        media_type="audio/mpeg",
        checksum="sha256:" + "a" * 64,
        duration_seconds=1.0,
        has_audio=True,
        created_at=datetime(2026, 11, 13, tzinfo=UTC),
    )


def ports(**overrides: Any) -> tuple[NarrationPorts, dict[str, Any]]:
    seen: dict[str, Any] = {
        "store": Store(),
        "documents": Documents(),
        "voice": Voice(),
        "provider_calls": 0,
        "provider_requests": [],
        "uploads": 0,
    }

    async def main_video(_p: str, _doc: Any, directory: Path) -> Path:
        path = directory / "main.mp4"
        path.write_bytes(b"x")
        return path

    async def transcribe(_path: Path) -> list[TranscriptSegment]:
        return [TranscriptSegment(text="kucing itu lari", start_seconds=0.0, end_seconds=1.0)]

    async def upload_audio(project: str, audio: bytes, _media: str) -> AssetRef:
        seen["uploads"] += 1
        seen.setdefault("uploaded", []).append(audio)
        return AssetRef(
            asset_id=f"asset_voice_{seen['uploads']}",
            project_id=project,
            kind="audio",
            duration_in_frames=60,
            has_audio=True,
            validation_state="ready",
        )

    class Provider:
        async def complete_json(self, **request: Any) -> dict[str, Any]:
            seen["provider_calls"] += 1
            seen["provider_requests"].append(request)
            if overrides.get("answers"):
                answer = overrides["answers"].pop(0)
                if isinstance(answer, Exception):
                    raise answer
                return answer
            return overrides.get("answer") or GOOD_ANSWER

    class Preferences:
        async def get_preference(self, _p: str, _s: str) -> Any:
            return overrides.get(
                "preference", SimpleNamespace(provider_id="openrouter", model_id="m")
            )

    class Library:
        """ws_one holds a whoosh; ws_two holds an item ws_one must never see."""

        items: ClassVar[dict[str, list[WorkspaceAsset]]] = {
            "ws_one": [library_item("lib_whoosh", "swipe")],
            "ws_two": [library_item("lib_theirs", "airhorn")],
        }

        async def list(self, workspace_id: str) -> list[WorkspaceAsset]:
            seen.setdefault("library_lists", []).append(workspace_id)
            return list(self.items.get(workspace_id, []))

        async def add_to_project(self, workspace_id: str, project: str, asset_id: str) -> Any:
            seen.setdefault("library_adds", []).append((workspace_id, project, asset_id))
            return EditorAsset(
                asset_id="asset_sfx",
                project_id=project,
                kind="audio",
                media_type="audio/mpeg",
                duration_in_frames=30,
                has_audio=True,
                validation_state="ready",
                checksum="sha256:" + "a" * 64,
            )

    async def workspace_of(_project: str) -> str | None:
        return overrides.get("workspace", "ws_one")

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
        library=Library(),
        workspace_of=workspace_of,
        prompts=None,
        preferences=Preferences(),
        provider=Provider(),
        prices=prices,
        intro_card=overrides.get("intro_card"),
    )
    return built, seen


def main_clip(document: EditDocumentV2) -> Any:
    main_tracks = {track.track_id for track in document.tracks if track.kind == "main_video"}
    return next(clip for clip in document.clips if clip.track_id in main_tracks)


def narrate_once(built: NarrationPorts, seen: dict[str, Any]) -> EditDocumentV2:
    activities = NarrationActivities(built)
    run(activities.write_script(NarrationScriptInput(**STEP.model_dump())))
    run(activities.voice(STEP))
    run(activities.write_draft(NarrationWriteInput(**STEP.model_dump())))
    return seen["documents"].written[-1]


def test_the_first_narration_starts_the_main_video_after_its_title_card() -> None:
    looked: list[Path] = []

    async def intro_card(video: Path) -> float | None:
        looked.append(video)
        return 0.4375

    built, seen = ports(intro_card=intro_card)
    written = narrate_once(built, seen)

    fps = written.canvas.fps
    # Up, never down: the card's last frame may lie just before the first read without it.
    assert main_clip(written).source_from_frame == math.ceil(0.4375 * fps)
    assert [path.name for path in looked] == ["main.mp4"]


def test_a_title_card_check_that_fails_leaves_the_main_video_where_it_was() -> None:
    async def intro_card(video: Path) -> float | None:
        raise RuntimeError("rapidocr broke")

    built, seen = ports(intro_card=intro_card)
    written = narrate_once(built, seen)

    before = main_clip(seen["documents"].document)
    assert main_clip(written).source_from_frame == before.source_from_frame


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

    assert result.code == "invalid_provider_output" and seen["provider_calls"] == 2
    assert seen["store"].status[-1] == ("failed", "invalid_provider_output")


@pytest.mark.parametrize(
    "refused",
    [{"beats": [{"beat": "outro", "text": "x"}]}, ProviderInvalidOutput("not JSON: 'x'")],
)
def test_a_refused_answer_is_asked_for_once_more(refused: Any) -> None:
    # One request on 2026-11-03 was refused and the same request, sent again, was usable.
    built, seen = ports(answers=[refused, GOOD_ANSWER])

    result = run(NarrationActivities(built).write_script(NarrationScriptInput(**STEP.model_dump())))

    assert result.code is None and seen["provider_calls"] == 2
    assert seen["store"].status[-1] == ("awaiting_approval", None)


def test_a_provider_outage_is_not_asked_again() -> None:
    built, seen = ports(answers=[ProviderUnavailable()])

    result = run(NarrationActivities(built).write_script(NarrationScriptInput(**STEP.model_dump())))

    assert result.code == "provider_unavailable" and seen["provider_calls"] == 1


def test_a_refused_answer_logs_why(caplog: pytest.LogCaptureFixture) -> None:
    built, _ = ports(answer={"beats": [{"beat": "outro", "text": "x"}]})

    with caplog.at_level("WARNING"):
        run(NarrationActivities(built).write_script(NarrationScriptInput(**STEP.model_dump())))

    assert "unknown beat" in caplog.text and "outro" in caplog.text


def test_the_script_request_carries_what_commenters_wrote() -> None:
    built, seen = ports()

    run(NarrationActivities(built).write_script(NarrationScriptInput(**STEP.model_dump())))

    user = seen["provider_requests"][0]["user"]
    assert "- lucu sekali" in user and "@andi" not in user


def test_the_script_only_hears_of_comments_shown_in_the_draft() -> None:
    # On stage1 (2026-11-03) the narration quoted comments 4 and 5 while only 3 had cards up.
    built, seen = ports()

    run(NarrationActivities(built).write_script(NarrationScriptInput(**STEP.model_dump())))

    user = seen["provider_requests"][0]["user"]
    assert "kartunya tidak tampil" not in user and "tanpa kartu" not in user


def test_a_hidden_card_is_not_a_comment_on_screen() -> None:
    built, seen = ports()
    document = seen["documents"].document
    seen["documents"].document = document.model_copy(
        update={
            "clips": [
                clip.model_copy(update={"hidden": clip.clip_id == "clip_comment_card_001"})
                for clip in document.clips
            ]
        }
    )

    run(NarrationActivities(built).write_script(NarrationScriptInput(**STEP.model_dump())))

    assert "lucu sekali" not in seen["provider_requests"][0]["user"]


def test_voicing_stitches_neighbours_and_writing_narrates_the_draft() -> None:
    built, seen = ports()
    activities = NarrationActivities(built)
    run(activities.write_script(NarrationScriptInput(**STEP.model_dump())))

    run(activities.voice(STEP))
    run(activities.write_draft(NarrationWriteInput(**STEP.model_dump())))

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
    run(activities.write_draft(NarrationWriteInput(**STEP.model_dump())))
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


def test_transcription_is_metered_in_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    from thoth_control_plane import metering

    recorded: list[tuple[str, str, float, str]] = []

    async def record(kind: str, key: str, quantity: float, unit: str) -> None:
        recorded.append((kind, key, quantity, unit))

    monkeypatch.setattr(metering, "record", record)
    built, _ = ports()

    run(NarrationActivities(built).transcribe(STEP))

    assert recorded == [("transcription", "faster_whisper", 1.0, "second")]


def test_beats_voiced_together_are_stitched_by_request_id() -> None:
    built, seen = ports()
    activities = NarrationActivities(built)
    run(activities.write_script(NarrationScriptInput(**STEP.model_dump())))
    counter = {"n": 0}
    real = seen["voice"].synthesize

    async def with_id(request):  # type: ignore[no-untyped-def]
        result = await real(request)
        counter["n"] += 1
        return result.model_copy(update={"request_id": f"req_{counter['n']}"})

    seen["voice"].synthesize = with_id
    run(activities.voice(STEP))

    requests = seen["voice"].requests
    assert [request.previous_request_ids for request in requests] == [
        None,
        ["req_1"],
        ["req_1", "req_2"],
    ]


# Style templates (spec 2026-11-10): a styled draft's script speaks in its style.
def styled_ports(template_id: str = "style_b", **overrides: Any):  # type: ignore[no-untyped-def]
    from thoth_control_plane.domain.edit_document_v2 import AppliedStyle

    built, seen = ports(**overrides)
    documents = seen["documents"]
    documents.document = documents.document.model_copy(
        update={"style": AppliedStyle(template_id=template_id, revision=1)}
    )
    return built, seen


def test_write_script_uses_the_style_prompt() -> None:
    from thoth_control_plane.domain.style_templates import BUILT_IN_STYLES

    built, seen = styled_ports()
    run(NarrationActivities(built).write_script(NarrationScriptInput(**STEP.model_dump())))
    system = seen["provider_requests"][0]["system"]
    assert BUILT_IN_STYLES["style_b"].narration.starter in system
    assert "card_line" in system


def test_the_style_overrides_target_length_and_sfx() -> None:
    from thoth_control_plane.domain import style_templates

    a = style_templates.BUILT_IN_STYLES["style_a"]
    longer = a.model_copy(
        update={
            "narration": a.narration.model_copy(update={"target_seconds": 60, "max_sfx_cues": 1})
        }
    )
    original = dict(style_templates.BUILT_IN_STYLES)
    style_templates.BUILT_IN_STYLES["style_a"] = longer
    try:
        built, seen = styled_ports("style_a")
        run(NarrationActivities(built).write_script(NarrationScriptInput(**STEP.model_dump())))
    finally:
        style_templates.BUILT_IN_STYLES.clear()
        style_templates.BUILT_IN_STYLES.update(original)
    user = seen["provider_requests"][0]["user"]
    assert "(60 seconds)" in user and "at most 1" in user


def test_an_unstyled_script_keeps_the_project_prompt() -> None:
    built, seen = ports()
    run(NarrationActivities(built).write_script(NarrationScriptInput(**STEP.model_dump())))
    assert "card_line" not in seen["provider_requests"][0]["system"]


def test_a_styled_script_keeps_the_title_card_for_its_preview() -> None:
    # Deferred minor (2026-11-10): the cut preview skips the title card the voice will skip.
    async def intro_card(video: Path) -> float | None:
        return 0.4375

    built, seen = styled_ports(intro_card=intro_card)
    run(NarrationActivities(built).write_script(NarrationScriptInput(**STEP.model_dump())))
    fps = seen["documents"].document.canvas.fps
    assert seen["store"].intro_frames == math.ceil(0.4375 * fps)


def test_every_voice_is_brought_to_one_level_before_it_is_stored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Operator, 2026-11-12: the narration was too quiet, and its beats ran 4 dB apart.
    levelled: list[str] = []

    def level(audio: bytes, media_type: str, **_: object) -> bytes:
        levelled.append(media_type)
        return b"LEVEL:" + audio

    monkeypatch.setattr("thoth_control_plane.activities.narration.normalize_loudness", level)
    built, seen = ports()
    activities = NarrationActivities(built)
    run(activities.write_script(NarrationScriptInput(**STEP.model_dump())))
    run(activities.voice(STEP))

    assert len(levelled) == 3
    assert seen["uploaded"] and all(audio.startswith(b"LEVEL:") for audio in seen["uploaded"])


def test_script_writer_lists_only_the_drafts_workspace_sfx() -> None:
    built, seen = ports()
    run(NarrationActivities(built).write_script(NarrationScriptInput(**STEP.model_dump())))
    user = seen["provider_requests"][0]["user"]
    assert "lib_whoosh: swipe" in user and "lib_theirs" not in user
    assert seen["library_lists"] == ["ws_one"]


def test_unknown_workspace_gives_no_sfx() -> None:
    built, seen = ports(workspace=None)
    run(NarrationActivities(built).write_script(NarrationScriptInput(**STEP.model_dump())))
    assert "No sound effects are available" in seen["provider_requests"][0]["user"]
    assert "library_lists" not in seen


def test_a_placed_cue_is_copied_from_the_workspace_library() -> None:
    built, seen = ports()
    document = narrate_once(built, seen)
    assert seen["library_adds"] == [("ws_one", "project_001", "lib_whoosh")]
    assert any(clip.clip_id == "clip_sfx_0" for clip in document.clips)
