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


def test_a_beats_cards_share_its_whole_window_end_to_end() -> None:
    # An imported draft layers its cards over the main video with gaps between them; mapping that
    # gappy span linearly left 0.4 s flashes of card and seconds of nothing (stage1, 2026-11-01).
    document = narrate_document(draft(), VOICES, [], PRESET, ROLES)

    first, second = clip(document, "clip_comment_card_000"), clip(document, "clip_comment_card_001")
    assert (first.from_frame, first.end_frame) == (258, 318)  # 60 and 60 frames share 120
    assert (second.from_frame, second.end_frame) == (318, 378)
    title = clip(document, "clip_001")  # the beat's only overlay fills it
    assert (title.from_frame, title.end_frame) == (258, 378)


def test_the_main_video_plays_under_the_hook_main_and_reaction_beats() -> None:
    document = narrate_document(draft(), VOICES, [], PRESET, ROLES)

    main = clip(document, "clip_main")
    assert (main.from_frame, main.duration_in_frames, main.source_from_frame) == (0, 378, 0)
    assert main.hold_after_source is False


def test_the_first_narration_runs_the_main_video_to_the_end_of_its_beats() -> None:
    # Cards reaching past the main clip once left it mapped short: 13.6 s of a 25.5 s window, then
    # black behind the cards (rev 18, rev 19; stage1, 2026-11-02).
    data = payload()
    next(item for item in data["clips"] if item["clip_id"] == "clip_main")["duration_in_frames"] = (
        150
    )

    main = clip(narrate_document(draft(data), VOICES, [], PRESET, ROLES), "clip_main")

    assert (main.from_frame, main.end_frame, main.source_from_frame) == (0, 378, 0)


def test_a_narrated_drafts_main_video_keeps_the_operators_layout() -> None:
    once = narrate_document(draft(), VOICES, [], PRESET, ROLES).model_dump(mode="python")
    main = next(item for item in once["clips"] if item["clip_id"] == "clip_main")
    main.update(duration_in_frames=189, volume_keyframes=[])  # the operator cut it to half

    again = narrate_document(EditDocumentV2.model_validate(once), VOICES, [], PRESET, ROLES)

    assert clip(again, "clip_main").end_frame == 189


def test_the_first_narration_starts_the_main_video_after_its_title_card() -> None:
    # Operator, 2026-11-08: the narrated draft's first frame showed the heading over the source's
    # own title card ("ROCKY GERUNG", 0.4 s); the draft now starts on the scene after it.
    main = clip(narrate_document(draft(), VOICES, [], PRESET, ROLES, intro_frames=13), "clip_main")

    assert (main.from_frame, main.source_from_frame) == (0, 13)


def test_a_title_card_inside_an_existing_trim_changes_nothing() -> None:
    data = payload()
    next(item for item in data["clips"] if item["clip_id"] == "clip_main")["source_from_frame"] = 30

    narrated = narrate_document(draft(data), VOICES, [], PRESET, ROLES, intro_frames=13)
    main = clip(narrated, "clip_main")

    assert main.source_from_frame == 30


def test_a_re_voice_keeps_where_the_operator_left_the_main_video() -> None:
    once = narrate_document(draft(), VOICES, [], PRESET, ROLES).model_dump(mode="python")

    again = narrate_document(
        EditDocumentV2.model_validate(once), VOICES, [], PRESET, ROLES, intro_frames=13
    )

    assert clip(again, "clip_main").source_from_frame == 0


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


def test_footage_on_the_b_roll_ducks_under_its_voice() -> None:
    # A footage movie's own sound played at full level over its narration (stage1, 2026-11-12).
    document = narrate_document(draft(), [*VOICES, voiced("footage", 4.0)], [], PRESET, ROLES)

    footage = clip(document, "clip_footage_000")
    assert PRESET.duck_volume in {key.volume for key in footage.volume_keyframes}
    # A still card has no sound to duck.
    assert clip(document, "clip_comment_card_000").volume_keyframes == []


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


def test_a_faded_video_clip_that_narration_shortens_keeps_its_fades_inside() -> None:
    # Final review 2026-11-08: video clips have fades since Tier 2, and a re-voice that shortens a
    # faded card must not fail validation after the voices are paid for.
    data = payload()
    card = next(item for item in data["clips"] if item["clip_id"] == "clip_comment_card_000")
    before = card["duration_in_frames"]
    card.update(fade_in_frames=before // 2, fade_out_frames=before // 2)

    shorter = [VOICES[0], VOICES[1], voiced("reactions", 2.0)]
    document = narrate_document(draft(data), shorter, [], PRESET, ROLES)

    shortened = clip(document, "clip_comment_card_000")
    assert shortened.duration_in_frames < before
    assert shortened.fade_in_frames + shortened.fade_out_frames <= shortened.duration_in_frames


def test_a_retimed_3x_clip_holds_where_its_source_ends() -> None:
    # Tier 3a: a sped-up clip spends its source faster, so the re-voice must hold the last frame
    # instead of failing validation after the voices are paid for.
    data = payload()
    next(item for item in data["clips"] if item["clip_id"] == "clip_main")["speed"] = 3.0

    main = clip(narrate_document(draft(data), VOICES, [], PRESET, ROLES), "clip_main")

    assert main.duration_in_frames == 378 and main.hold_after_source is True


def test_a_revoice_that_shortens_the_draft_keeps_its_markers_inside() -> None:
    # Tier 3a: a marker past the new end would fail validation after the voices are paid for.
    data = payload()
    # A long draft, so the voice-over makes it shorter.
    data["canvas"]["duration_in_frames"] = 2000
    data["markers"] = [{"marker_id": "marker_late", "frame": 1999}]

    document = narrate_document(draft(data), VOICES, [], PRESET, ROLES)

    assert document.canvas.duration_in_frames < 2000
    assert [m.frame for m in document.markers] == [document.canvas.duration_in_frames - 1]


def test_retime_stretches_moves() -> None:
    data = payload()
    main = next(c for c in data["clips"] if c["clip_id"] == "clip_main")
    old = main["duration_in_frames"]
    main["moves"] = [{"frame": 0, "scale": 1.0}, {"frame": old - 1, "scale": 1.2}]
    document = narrate_document(draft(data), VOICES, [], PRESET, ROLES)
    retimed = clip(document, "clip_main")
    new = retimed.duration_in_frames
    assert [move.frame for move in retimed.moves] == [0, min((old - 1) * new // old, new - 1)]


# Style templates (spec 2026-11-10): the narration writes captions and cuts in the draft's style.
def test_sentence_ends_come_from_the_voice() -> None:
    from thoth_control_plane.assembly.narration_timeline import sentence_ends

    timed = [
        WordTiming(text="Satu", start_seconds=0.0, end_seconds=0.4),
        WordTiming(text="dua.", start_seconds=0.5, end_seconds=1.0),
        WordTiming(text="Tiga", start_seconds=1.2, end_seconds=1.5),
        WordTiming(text="empat?", start_seconds=1.6, end_seconds=2.0),
    ]
    assert sentence_ends(timed, 100, 30) == [130, 160]


def test_a_styled_narration_uses_the_style_caption_and_cuts() -> None:
    from thoth_control_plane.domain.style_templates import BUILT_IN_STYLES

    b = BUILT_IN_STYLES["style_b"]
    styled = narrate_document(draft(), VOICES, [], PRESET, ROLES, style=b)
    captions = [c for c in styled.clips if isinstance(c, TimelineCaptionClip)]
    assert captions and {c.style_slot for c in captions} == {"kinetic"}
    assert styled.style is not None and styled.style.template_id == "style_b"
    shots = [
        c
        for c in styled.clips
        if isinstance(c, TimelineVideoClip) and c.clip_id.startswith("clip_style_")
    ]
    assert shots and all(c.duration_in_frames <= 120 for c in shots)


def test_a_styled_narration_cuts_on_real_sentence_ends() -> None:
    from thoth_control_plane.assembly.narration_timeline import sentence_ends
    from thoth_control_plane.domain.style_templates import BUILT_IN_STYLES

    text = "satu dua tiga. empat lima enam."
    two = [voiced("hook", 2.0), voiced("main", 6.0, text), voiced("reactions", 4.0)]
    styled = narrate_document(draft(), two, [], PRESET, ROLES, style=BUILT_IN_STYLES["style_a"])
    main_voice = clip(styled, "clip_narration_main")
    ends = sentence_ends(words(text, 6.0), main_voice.from_frame, FPS)
    starts = {
        c.from_frame
        for c in styled.clips
        if isinstance(c, TimelineVideoClip) and c.clip_id.startswith("clip_style_main")
    }
    # A cut falls on the latest sentence end a shot can reach (spec 2026-11-10, 4).
    assert set(ends) & starts


def test_a_styled_narration_places_the_card_lines() -> None:
    from thoth_control_plane.domain.edit_document_v2 import TimelineTextClip
    from thoth_control_plane.domain.style_templates import BUILT_IN_STYLES

    styled = narrate_document(
        draft(),
        VOICES,
        [],
        PRESET,
        ROLES,
        style=BUILT_IN_STYLES["style_b"],
        card_lines={"hook": "Kok bisa ya?"},
    )
    cards = [c for c in styled.clips if isinstance(c, TimelineTextClip) and c.style_slot == "card"]
    assert [c.heading for c in cards] == ["Kok bisa ya?"]


def _timed(*spans: tuple[str, float, float]) -> list[WordTiming]:
    return [WordTiming(text=t, start_seconds=a, end_seconds=b) for t, a, b in spans]


def test_a_card_shows_when_the_voice_says_its_line() -> None:
    # Stage1, 2026-11-12: the card came at the beat's start while the voice said something else.
    from thoth_control_plane.domain.edit_document_v2 import TimelineTextClip
    from thoth_control_plane.domain.style_templates import BUILT_IN_STYLES

    main = VoicedBeat(
        beat="main",
        asset=audio("asset_voice_main", 5.0),
        duration_seconds=5.0,
        words=_timed(
            ("Ternyata", 0.0, 0.4),
            ("ini", 0.5, 0.7),
            ("gara-gara", 0.8, 1.4),
            ("kabar.", 1.5, 2.0),
            ("Waduh,", 2.6, 3.0),
            ("beneran", 3.1, 3.5),
            ("mau", 3.6, 3.8),
            ("mundur?", 3.9, 4.6),
        ),
    )
    styled = narrate_document(
        draft(),
        [VOICES[0], main, VOICES[2]],
        [],
        PRESET,
        ROLES,
        style=BUILT_IN_STYLES["style_b"],
        card_lines={"main": "Beneran mau mundur?", "reactions": "Tidak ada yang cocok"},
    )
    cards = {
        c.heading: c.from_frame
        for c in styled.clips
        if isinstance(c, TimelineTextClip) and c.style_slot == "card"
    }
    voice = next(c for c in styled.clips if c.clip_id == "clip_narration_main")
    # "beneran", the first word of the line the voice says.
    assert cards["Beneran mau mundur?"] == voice.from_frame + round(3.1 * FPS)
    # A line the voice never says keeps the old place.
    assert "Tidak ada yang cocok" in cards


def test_a_card_lands_on_its_closest_sentence_at_the_first_word_it_repeats() -> None:
    # The stored draft of 2026-11-12: a long sentence shared as many words as the short reaction.
    from thoth_control_plane.assembly.narration_timeline import spoken_at

    words = _timed(
        ("pakai", 0.0, 0.3),
        ("dokumen", 0.4, 0.8),
        ("dari", 0.9, 1.0),
        ("SD", 1.1, 1.3),
        ("sampai", 1.4, 1.7),
        ("S1.", 1.8, 2.2),
        ("Hah,", 2.5, 2.7),
        ("sampai", 2.8, 3.1),
        ("SD", 3.2, 3.4),
        ("juga", 3.5, 3.6),
        ("dibawa?", 3.7, 4.2),
        ("karena", 4.5, 4.8),
        ("menentukan", 4.9, 5.4),
        ("siapa", 5.5, 5.8),
        ("yang", 5.9, 6.0),
        ("bakal", 6.1, 6.3),
        ("bertahan.", 6.4, 7.0),
    )
    assert spoken_at("Sampai dokumen SD dibawa?", words, 100, FPS) == 100 + round(2.8 * FPS)
    assert spoken_at("Siapa yang bakal bertahan?", words, 100, FPS) == 100 + round(5.5 * FPS)
    assert spoken_at("Netizen kok curiga?", words, 100, FPS) is None


def test_a_revoice_of_a_styled_draft_keeps_the_hand_edits() -> None:
    # Final review (operator, 2026-11-10): the style cuts once, from its first voice; a re-voice
    # only retimes, so shots the operator changed afterwards stay as they left them.
    from tests.domain.test_timeline_operations import op
    from thoth_control_plane.domain.edit_document_operations import apply_edit_operations
    from thoth_control_plane.domain.style_templates import BUILT_IN_STYLES

    a = BUILT_IN_STYLES["style_a"]
    first = narrate_document(draft(), VOICES, [], PRESET, ROLES, style=a)
    shot = next(c for c in first.clips if c.clip_id.startswith("clip_style_main"))
    edited = apply_edit_operations(first, [op("set_clip_dim", clip_id=shot.clip_id, dim=0.3)])
    again = narrate_document(edited, VOICES, [], PRESET, ROLES, style=a)
    kept = next((c for c in again.clips if c.clip_id == shot.clip_id), None)
    assert kept is not None and kept.dim == 0.3


def test_captions_page_by_the_styles_words_per_caption() -> None:
    # Deferred minor (2026-11-10): Style B pages its captions three words at a time.
    from thoth_control_plane.domain.style_templates import BUILT_IN_STYLES

    fast = [voiced("main", 2.0, "satu dua tiga empat lima enam tujuh delapan")]
    plain = clip(narrate_document(draft(), fast, [], PRESET, ROLES), "clip_caption_narration_main")
    styled = clip(
        narrate_document(draft(), fast, [], PRESET, ROLES, style=BUILT_IN_STYLES["style_b"]),
        "clip_caption_narration_main",
    )
    assert isinstance(plain, TimelineCaptionClip) and isinstance(styled, TimelineCaptionClip)
    assert max(len(cue.words) for cue in plain.cues) == 4
    assert max(len(cue.words) for cue in styled.cues) == 3


# Operator, 2026-11-10: a re-voice re-cuts a beat by the style when its voice changed and none
# of its shots were touched by hand; a beat with hand edits only stretches, and says so.
def _longer_main() -> VoicedBeat:
    return VoicedBeat(
        beat="main",
        asset=audio("asset_voice_main_v2", 12.0),
        duration_seconds=12.0,
        words=words("satu dua tiga. empat lima enam.", 12.0),
    )


def _main_beat_shots(document: EditDocumentV2) -> list[TimelineVideoClip]:
    from thoth_control_plane.domain.story_beats import clip_beats

    beats = clip_beats(document, ROLES)
    return [
        c
        for c in document.clips
        if isinstance(c, TimelineVideoClip)
        and beats.get(c.clip_id) == "main"
        and c.position is None
        and not c.hidden
    ]


def test_a_revoice_recuts_an_untouched_beat_by_the_style() -> None:
    from thoth_control_plane.domain.style_templates import BUILT_IN_STYLES

    b = BUILT_IN_STYLES["style_b"]
    first = narrate_document(draft(), VOICES, [], PRESET, ROLES, style=b)
    again = narrate_document(
        first, [VOICES[0], _longer_main(), VOICES[2]], [], PRESET, ROLES, style=b
    )
    shots = _main_beat_shots(again)
    assert shots and all(c.duration_in_frames <= 90 + 30 for c in shots)
    assert again.style is not None and again.style.kept == []


def test_a_revoice_stretches_a_hand_edited_beat_and_says_so() -> None:
    from tests.domain.test_timeline_operations import op
    from thoth_control_plane.domain.edit_document_operations import apply_edit_operations
    from thoth_control_plane.domain.style_templates import BUILT_IN_STYLES

    b = BUILT_IN_STYLES["style_b"]
    first = narrate_document(draft(), VOICES, [], PRESET, ROLES, style=b)
    shot = _main_beat_shots(first)[0]
    edited = apply_edit_operations(first, [op("set_clip_dim", clip_id=shot.clip_id, dim=0.3)])
    again = narrate_document(
        edited, [VOICES[0], _longer_main(), VOICES[2]], [], PRESET, ROLES, style=b
    )
    kept = next((c for c in again.clips if c.clip_id == shot.clip_id), None)
    assert kept is not None and kept.dim == 0.3
    assert again.style is not None and again.style.kept == ["main"]
