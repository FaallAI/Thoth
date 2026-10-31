"""The narrated draft: beats retimed to their voice, plus narration, captions, ducking and SFX.

Spec 2026-10-31 (auto-draft, the narrated draft), section 5. The draft is the shared Story case
document: a hook, the main video, reaction cards, footage, and two clips with no beat.
"""

from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from thoth_control_plane.assembly.narration_timeline import (
    PlacedSfx,
    VoicedBeat,
    narrate_document,
)
from thoth_control_plane.domain.edit_document_v2 import (
    AssetRef,
    EditDocumentV2,
    TimelineAudioClip,
    TimelineCaptionClip,
    TimelineVideoClip,
)
from thoth_control_plane.domain.narration import NarrationPreset, SfxCue
from thoth_control_plane.voice.ports import WordTiming

FPS = 30
CASES = json.loads(
    (Path(__file__).parents[3] / "dashboard/src/features/studio/story_beat_cases.json").read_text(
        "utf-8"
    )
)
PRESET = NarrationPreset()
LEAD_IN = math.ceil(PRESET.lead_in_seconds * FPS)  # 48
#: Drafts made before Story mode name their beat through the inventory, as Studio reads them.
ROLES = CASES["cases"][0]["inventory_roles"]


def payload() -> dict[str, Any]:
    return deepcopy(CASES["cases"][0]["document"])


def draft(data: dict[str, Any] | None = None) -> EditDocumentV2:
    return EditDocumentV2.model_validate(data or payload())


def audio(asset_id: str, seconds: float) -> AssetRef:
    return AssetRef(
        asset_id=asset_id,
        project_id="project_001",
        kind="audio",
        duration_in_frames=math.ceil(seconds * FPS),
        has_audio=True,
        validation_state="ready",
    )


def words(text: str, seconds: float) -> list[WordTiming]:
    tokens = text.split()
    step = seconds / len(tokens)
    return [
        WordTiming(text=token, start_seconds=index * step, end_seconds=(index + 0.8) * step)
        for index, token in enumerate(tokens)
    ]


def voiced(beat: str, seconds: float, text: str = "satu dua tiga empat lima enam") -> VoicedBeat:
    return VoicedBeat(
        beat=beat,  # type: ignore[arg-type]
        asset=audio(f"asset_voice_{beat}", seconds),
        duration_seconds=seconds,
        words=words(text, seconds),
    )


VOICES = [voiced("hook", 2.0), voiced("main", 5.0), voiced("reactions", 4.0)]


def clip(document: EditDocumentV2, clip_id: str) -> Any:
    return next(item for item in document.clips if item.clip_id == clip_id)


def narration_clips(document: EditDocumentV2) -> dict[str, TimelineAudioClip]:
    narration = {track.track_id for track in document.tracks if track.kind == "narration"}
    return {
        item.clip_id: item
        for item in document.clips
        if isinstance(item, TimelineAudioClip) and item.track_id in narration
    }


# Windows in story order: hook ceil((2.0 + 1.6) * 30) = 108, main 150, reactions 120, and
# footage (no voice) keeps its 200 frames: 0-108, 108-258, 258-378, 378-578.


def test_beats_play_in_story_order_each_as_long_as_its_voice() -> None:
    document = narrate_document(draft(), VOICES, [], PRESET, ROLES)

    assert document.canvas.duration_in_frames == 578
    voices = narration_clips(document)
    assert (
        voices["clip_narration_hook"].from_frame,
        voices["clip_narration_hook"].duration_in_frames,
    ) == (LEAD_IN, 60)
    assert (
        voices["clip_narration_main"].from_frame,
        voices["clip_narration_main"].duration_in_frames,
    ) == (108, 150)
    assert (
        voices["clip_narration_reactions"].from_frame,
        voices["clip_narration_reactions"].duration_in_frames,
    ) == (258, 120)
    footage = clip(document, "clip_footage_000")
    assert (footage.from_frame, footage.duration_in_frames) == (378, 200)


def test_a_beats_clips_keep_their_order_inside_the_new_window() -> None:
    document = narrate_document(draft(), VOICES, [], PRESET, ROLES)

    first, second = clip(document, "clip_comment_card_000"), clip(document, "clip_comment_card_001")
    assert 258 <= first.from_frame < second.from_frame < 378
    assert first.end_frame <= 378 and second.end_frame <= 378
    hook = clip(document, "clip_hook")
    assert (hook.from_frame, hook.end_frame) == (0, 108)


def test_the_main_video_plays_under_the_hook_main_and_reaction_beats() -> None:
    document = narrate_document(draft(), VOICES, [], PRESET, ROLES)

    main = clip(document, "clip_main")
    assert (main.from_frame, main.duration_in_frames, main.source_from_frame) == (0, 378, 0)
    assert main.hold_after_source is False


def test_a_main_video_shorter_than_its_beats_holds_its_last_frame() -> None:
    data = payload()
    next(item for item in data["clips"] if item["clip_id"] == "clip_main")["source_from_frame"] = (
        600
    )

    main = clip(narrate_document(draft(data), VOICES, [], PRESET, ROLES), "clip_main")

    assert main.duration_in_frames == 378 and main.hold_after_source is True


def test_clips_with_no_beat_scale_with_the_whole_timeline() -> None:
    document = narrate_document(draft(), VOICES, [], PRESET, ROLES)

    title = clip(document, "clip_002")  # 150-300 of 300 frames
    assert title.from_frame == 289 and title.end_frame <= 578


def test_the_narrated_draft_has_one_scene_over_the_whole_canvas() -> None:
    document = narrate_document(draft(), VOICES, [], PRESET, ROLES)

    assert [
        (scene.scene_id, scene.start_frame, scene.duration_in_frames) for scene in document.scenes
    ] == [("scene_001", 0, 578)]
    assert {item.scene_id for item in document.clips if item.clip_id != "clip_001"} == {None}


def test_captions_are_word_pages_timed_by_the_voice() -> None:
    document = narrate_document(draft(), VOICES, [], PRESET, ROLES)

    caption = clip(document, "clip_caption_narration_main")
    assert isinstance(caption, TimelineCaptionClip)
    assert caption.style_slot == "word_highlight"
    assert (caption.from_frame, caption.duration_in_frames) == (108, 150)
    assert all(1 <= len(cue.words) <= 4 for cue in caption.cues)
    assert [word.text for cue in caption.cues for word in cue.words] == [
        "satu",
        "dua",
        "tiga",
        "empat",
        "lima",
        "enam",
    ]
    assert all(cue.text == " ".join(word.text for word in cue.words) for cue in caption.cues)


def test_the_main_video_ducks_under_speech_and_leaks_in_pauses() -> None:
    paused = VoicedBeat(
        beat="main",
        asset=audio("asset_voice_main", 5.0),
        duration_seconds=5.0,
        words=[
            WordTiming(text="sebelum", start_seconds=0.0, end_seconds=1.0),
            WordTiming(text="jeda", start_seconds=2.0, end_seconds=3.0),  # a 1 s pause
        ],
    )
    document = narrate_document(draft(), [VOICES[0], paused, VOICES[2]], [], PRESET, ROLES)

    keyframes = [(key.frame, key.volume) for key in clip(document, "clip_main").volume_keyframes]
    assert keyframes[0] == (0, 1.0)
    assert (LEAD_IN, PRESET.duck_volume) in keyframes or any(
        frame >= LEAD_IN and volume == PRESET.duck_volume for frame, volume in keyframes[:4]
    )
    assert PRESET.leak_volume in {volume for _, volume in keyframes}
    assert keyframes[-1][1] == 1.0


def test_sfx_land_on_their_word_and_voices_fade_at_their_edges() -> None:
    cue = SfxCue(sfx_id="impact", beat="main", moment="emphasis_word", word_index=2)
    sfx = PlacedSfx(cue=cue, asset=audio("asset_sfx_impact", 1.0), duration_seconds=1.0)

    document = narrate_document(draft(), VOICES, [sfx], PRESET, ROLES)

    placed = clip(document, "clip_sfx_0")
    third_word = VOICES[1].words[2].start_seconds
    assert placed.from_frame == 108 + round(third_word * FPS)
    assert (placed.fade_in_frames, placed.fade_out_frames) == (2, 2)
    assert narration_clips(document)["clip_narration_main"].fade_in_frames == 2


def test_imported_subtitles_blur_once_narration_covers_the_speech() -> None:
    data = payload()
    main = next(item for item in data["clips"] if item["clip_id"] == "clip_main")
    main["blur_regions"] = [{"x": 0.1, "y": 0.8, "w": 0.8, "h": 0.1}]

    narrated = clip(narrate_document(draft(data), VOICES, [], PRESET, ROLES), "clip_main")

    assert isinstance(narrated, TimelineVideoClip) and narrated.blur_enabled is True


def test_narrating_a_narrated_draft_again_changes_nothing() -> None:
    once = narrate_document(draft(), VOICES, [], PRESET, ROLES)

    assert narrate_document(once, VOICES, [], PRESET, ROLES) == once


def test_re_voicing_one_beat_moves_only_the_beats_after_it() -> None:
    once = narrate_document(draft(), VOICES, [], PRESET, ROLES)
    longer = [VOICES[0], voiced("main", 6.0), VOICES[2]]

    again = narrate_document(once, longer, [], PRESET, ROLES)

    voices = narration_clips(again)
    assert voices["clip_narration_hook"].from_frame == LEAD_IN
    assert (
        voices["clip_narration_main"].from_frame,
        voices["clip_narration_main"].duration_in_frames,
    ) == (108, 180)
    assert voices["clip_narration_reactions"].from_frame == 288
    assert again.canvas.duration_in_frames == 608


def test_an_edited_draft_follows_its_current_beats() -> None:
    data = payload()
    data["clips"] = [
        item
        for item in data["clips"]
        if item["clip_id"] not in {"clip_hook", "clip_comment_card_001"}
    ]
    for track in data["tracks"]:
        track["clip_ids"] = [
            cid for cid in track["clip_ids"] if cid not in {"clip_hook", "clip_comment_card_001"}
        ]

    document = narrate_document(
        draft(data), [voiced("main", 5.0), voiced("reactions", 4.0)], [], PRESET, ROLES
    )

    voices = narration_clips(document)
    assert voices["clip_narration_main"].from_frame == LEAD_IN
    assert "clip_hook" not in {item.clip_id for item in document.clips}


def test_a_voiced_beat_without_material_still_gets_its_window() -> None:
    document = narrate_document(draft(), [*VOICES, voiced("outro", 2.0)], [], PRESET, ROLES)

    outro = narration_clips(document)["clip_narration_outro"]
    assert outro.from_frame == 578 and document.canvas.duration_in_frames == 638


@pytest.mark.parametrize("hidden", ["clip_footage_000", "clip_comment_card_000"])
def test_hidden_clips_stay_valid_and_hidden(hidden: str) -> None:
    data = payload()
    next(item for item in data["clips"] if item["clip_id"] == hidden)["hidden"] = True

    document = narrate_document(draft(data), VOICES, [], PRESET, ROLES)

    assert clip(document, hidden).hidden is True
    assert EditDocumentV2.model_validate(document.model_dump(mode="json")) == document


# --- Final review fixes (I5, I6) ---


def with_music(seconds_of_asset: int = 4) -> dict[str, Any]:
    """An operator added a music clip under the reactions cards, as long as its asset."""
    data = payload()
    frames = seconds_of_asset * FPS
    data["asset_refs"].append(
        {
            "asset_id": "asset_music",
            "project_id": "project_001",
            "kind": "audio",
            "duration_in_frames": frames,
            "has_audio": True,
            "validation_state": "ready",
        }
    )
    data["clips"].append(
        {
            "kind": "audio",
            "clip_id": "clip_music_op",
            "track_id": "track_music",
            "scene_id": None,
            "from_frame": 60,
            "duration_in_frames": frames,
            "ownership": "user_edited",
            "hidden": False,
            "locked": False,
            "source_role": "comment_card",
            "asset_id": "asset_music",
            "source_from_frame": 0,
            "volume": 0.5,
            "fade_in_frames": 0,
            "fade_out_frames": 0,
        }
    )
    for track in data["tracks"]:
        if track["track_id"] == "track_music":
            track["clip_ids"].append("clip_music_op")
    return data


def test_an_operator_audio_clip_never_outgrows_its_asset() -> None:
    longer = [VOICES[0], VOICES[1], voiced("reactions", 9.0)]

    document = narrate_document(draft(with_music()), longer, [], PRESET, ROLES)

    music = clip(document, "clip_music_op")
    assert music.duration_in_frames <= 4 * FPS


def test_re_voicing_keeps_the_operators_narration_layer_edits() -> None:
    once = narrate_document(draft(), VOICES, [], PRESET, ROLES)
    edited = once.model_dump(mode="python")
    for item in edited["clips"]:
        if item["clip_id"] == "clip_narration_hook":
            item["volume"] = 0.7
        if item["clip_id"] == "clip_caption_narration_hook":
            item["style_slot"] = "caption_default"
            item["cues"][0]["text"] = "Teks diperbaiki"
    again = narrate_document(
        EditDocumentV2.model_validate(edited),
        [VOICES[0], voiced("main", 6.0), VOICES[2]],
        [],
        PRESET,
        ROLES,
    )

    assert clip(again, "clip_narration_hook").volume == 0.7
    caption = clip(again, "clip_caption_narration_hook")
    assert caption.style_slot == "caption_default" and caption.cues[0].text == "Teks diperbaiki"


def test_re_voicing_keeps_a_deleted_sfx_deleted_and_blur_switched_off() -> None:
    cue = SfxCue(sfx_id="impact", beat="main", moment="emphasis_word", word_index=2)
    sfx = [PlacedSfx(cue=cue, asset=audio("asset_sfx_impact", 1.0), duration_seconds=1.0)]
    data = payload()
    next(item for item in data["clips"] if item["clip_id"] == "clip_main")["blur_regions"] = [
        {"x": 0.1, "y": 0.8, "w": 0.8, "h": 0.1}
    ]
    once = narrate_document(draft(data), VOICES, sfx, PRESET, ROLES).model_dump(mode="python")
    once["clips"] = [item for item in once["clips"] if item["clip_id"] != "clip_sfx_0"]
    for track in once["tracks"]:
        track["clip_ids"] = [cid for cid in track["clip_ids"] if cid != "clip_sfx_0"]
    next(item for item in once["clips"] if item["clip_id"] == "clip_main")["blur_enabled"] = False

    # A re-voice keeps the operator's SFX as they left them.
    again = narrate_document(
        EditDocumentV2.model_validate(once), VOICES, sfx, PRESET, ROLES, place_sfx=False
    )

    assert "clip_sfx_0" not in {item.clip_id for item in again.clips}
    assert clip(again, "clip_main").blur_enabled is False


def test_a_clip_whose_beat_came_from_its_scene_keeps_that_beat_after_narration() -> None:
    from thoth_control_plane.domain.story_beats import clip_beats

    once = narrate_document(draft(), VOICES, [], PRESET, ROLES)

    assert clip_beats(once, ROLES).get("clip_001") == "reactions"
    again = narrate_document(once, [VOICES[0], voiced("main", 6.0), VOICES[2]], [], PRESET, ROLES)
    title = clip(again, "clip_001")
    assert 288 <= title.from_frame < 408  # still inside the reactions window after the shift


def test_a_recreated_narration_places_the_new_scripts_sfx() -> None:
    """Narration restarted (operator, 2026-10-31): the SFX shown at approval are the ones placed."""
    old = SfxCue(sfx_id="impact", beat="main", moment="emphasis_word", word_index=2)
    new = SfxCue(sfx_id="ding", beat="reactions", moment="comment_appear")
    once = narrate_document(
        draft(),
        VOICES,
        [PlacedSfx(cue=old, asset=audio("asset_sfx_impact", 1.0), duration_seconds=1.0)],
        PRESET,
        ROLES,
    )

    again = narrate_document(
        once,
        VOICES,
        [PlacedSfx(cue=new, asset=audio("asset_sfx_ding", 1.0), duration_seconds=1.0)],
        PRESET,
        ROLES,
        place_sfx=True,
    )

    sfx_clips = [item for item in again.clips if item.clip_id.startswith("clip_sfx_")]
    assert [item.asset_id for item in sfx_clips] == ["asset_sfx_ding"]
    assert sfx_clips[0].from_frame == 258
