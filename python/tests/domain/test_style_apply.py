"""Applying a style: a draft's cuts and look rebuilt from its materials (spec 2026-11-10, 6)."""

from __future__ import annotations

from typing import Any

from tests.assembly.test_narration_timeline import PRESET, ROLES, VOICES, draft, payload
from tests.domain.test_timeline_operations import op
from thoth_control_plane.assembly.narration_timeline import narrate_document
from thoth_control_plane.domain.edit_document_operations import apply_edit_operations
from thoth_control_plane.domain.edit_document_v2 import (
    EditDocumentV2,
    TimelineCaptionClip,
    TimelineTextClip,
    TimelineVideoClip,
)
from thoth_control_plane.domain.planner_assign import BeatAssignment, PlannedCard, PlannedShot
from thoth_control_plane.domain.story_beats import beat_spans, clip_beats
from thoth_control_plane.domain.style_apply import style_operations
from thoth_control_plane.domain.style_templates import BUILT_IN_STYLES

A = BUILT_IN_STYLES["style_a"]
B = BUILT_IN_STYLES["style_b"]


def narrated(data: dict[str, Any] | None = None) -> EditDocumentV2:
    return narrate_document(draft(data), VOICES, [], PRESET, ROLES)


def styled(document: EditDocumentV2, template=A, **kwargs: Any) -> EditDocumentV2:  # type: ignore[no-untyped-def]
    operations = style_operations(document, template, ROLES, **kwargs)
    assets = {ref.asset_id: ref for ref in document.asset_refs}
    return apply_edit_operations(document, operations, resolved_assets=assets)


def full_frame_shots(document: EditDocumentV2) -> list[TimelineVideoClip]:
    beats = clip_beats(document, ROLES)
    return [
        clip
        for clip in document.clips
        if isinstance(clip, TimelineVideoClip)
        and clip.clip_id in beats
        and clip.position is None
        and not clip.hidden
        and not clip.locked
    ]


def test_style_a_rebuilds_each_beat() -> None:
    document = styled(narrated())
    shots = full_frame_shots(document)
    assert shots
    longest = round(A.cuts.max_shot_seconds * 30) + round(A.cuts.min_shot_seconds * 30)
    assert all(shot.duration_in_frames <= longest for shot in shots)
    assert all(shot.moves for shot in shots)
    captions = [clip for clip in document.clips if isinstance(clip, TimelineCaptionClip)]
    assert captions and {clip.style_slot for clip in captions} == {"boxed"}
    assert document.style is not None and document.style.template_id == "style_a"


def test_style_b_rebuilds_each_beat() -> None:
    document = styled(narrated(), B)
    shots = full_frame_shots(document)
    assert shots and all(shot.dim == 0.45 for shot in shots)
    assert all(shot.duration_in_frames <= 90 + 30 for shot in shots)
    captions = [clip for clip in document.clips if isinstance(clip, TimelineCaptionClip)]
    assert {clip.style_slot for clip in captions} == {"kinetic"}


def test_a_locked_clip_stays() -> None:
    data = payload()
    footage = next(c for c in data["clips"] if c["clip_id"] == "clip_footage_000")
    footage["locked"] = True
    before = narrated(data)
    after = styled(before)
    locked = next(c for c in before.clips if c.clip_id == "clip_footage_000")
    assert next(c for c in after.clips if c.clip_id == "clip_footage_000") == locked


def test_a_hidden_clip_is_not_placed_again() -> None:
    data = payload()
    footage = next(c for c in data["clips"] if c["clip_id"] == "clip_footage_000")
    footage["hidden"] = True
    after = styled(narrated(data))
    using = [c for c in after.clips if getattr(c, "asset_id", None) == "asset_vid_long"]
    assert [c.clip_id for c in using] == ["clip_footage_000"]


def test_clips_outside_beats_and_narration_stay() -> None:
    before = narrated()
    after = styled(before)
    beats = clip_beats(before, ROLES)
    kept = {
        c.clip_id: c
        for c in before.clips
        if c.clip_id not in beats and not isinstance(c, TimelineCaptionClip)
    }
    assert kept
    for clip_id, clip in kept.items():
        assert next(c for c in after.clips if c.clip_id == clip_id) == clip


def test_style_b_card_lines_become_cards() -> None:
    before = narrated()
    hook_start = min(
        c.from_frame for c in before.clips if clip_beats(before, ROLES).get(c.clip_id) == "hook"
    )
    after = styled(before, B, card_lines={"hook": "Kok bisa ya?"})
    cards = [c for c in after.clips if isinstance(c, TimelineTextClip) and c.style_slot == "card"]
    assert [(card.heading, card.from_frame) for card in cards] == [("Kok bisa ya?", hook_start)]


def test_b_after_a_gives_the_same_as_b_alone() -> None:
    def picture(document: EditDocumentV2) -> list[tuple[Any, ...]]:
        return sorted(
            (
                shot.track_id,
                shot.from_frame,
                shot.duration_in_frames,
                shot.asset_id,
                shot.source_from_frame,
                shot.dim,
                shot.background,
                tuple((m.frame, m.scale) for m in shot.moves),
            )
            for shot in full_frame_shots(document)
        )

    alone = styled(narrated(), B)
    after_a = styled(styled(narrated()), B)
    assert picture(after_a) == picture(alone)


# Final review fixes (2026-11-10).
def _main_shots(document: EditDocumentV2) -> list[TimelineVideoClip]:
    main = {t.track_id for t in document.tracks if t.kind == "main_video"}
    return [c for c in document.clips if isinstance(c, TimelineVideoClip) and c.track_id in main]


def test_a_style_keeps_the_main_videos_subtitle_blur() -> None:
    data = payload()
    main = next(c for c in data["clips"] if c["clip_id"] == "clip_main")
    main["blur_enabled"] = True
    main["blur_regions"] = [{"x": 0.1, "y": 0.65, "w": 0.8, "h": 0.09}]
    shots = [c for c in _main_shots(styled(narrated(data))) if not c.hidden]
    assert len(shots) > 1
    assert all(s.blur_enabled and [r.y for r in s.blur_regions] == [0.65] for s in shots)


def test_a_styles_heading_place_leaves_a_credit_in_its_corner() -> None:
    # A credit is no heading: Style A's title_top for the hook must not lift it (2026-11-12).
    data = payload()
    hook = next(c for c in data["clips"] if c["clip_id"] == "clip_hook")
    hook["style_slot"] = "credit"
    after = styled(narrated(data))
    assert next(c for c in after.clips if c.clip_id == "clip_hook").style_slot == "credit"


def test_a_style_keeps_a_long_videos_many_subtitle_blurs() -> None:
    # A real draft's OCR gave its main video 22 timed blur regions (stage1, 2026-11-12).
    data = payload()
    main = next(c for c in data["clips"] if c["clip_id"] == "clip_main")
    main["blur_enabled"] = True
    main["blur_regions"] = [
        {"x": 0.1, "y": 0.65, "w": 0.8, "h": 0.09, "from_frame": i * 10, "to_frame": i * 10 + 9}
        for i in range(22)
    ]
    shots = [c for c in _main_shots(styled(narrated(data))) if not c.hidden]
    assert shots and all(len(s.blur_regions) == 22 for s in shots)


def test_a_hidden_middle_shot_is_built_around() -> None:
    once = styled(narrated())
    middle = sorted(_main_shots(once), key=lambda c: c.from_frame)[1]
    hidden = apply_edit_operations(
        once,
        [op("set_clip_hidden", operation_id="op_hide", clip_id=middle.clip_id, hidden=True)],
    )
    again = styled(hidden)
    assert next(c for c in again.clips if c.clip_id == middle.clip_id) == next(
        c for c in hidden.clips if c.clip_id == middle.clip_id
    )
    renarrated = narrate_document(hidden, VOICES, [], PRESET, ROLES, style=A)
    assert renarrated.style is not None


def test_a_locked_middle_shot_is_built_around() -> None:
    once = styled(narrated())
    middle = sorted(_main_shots(once), key=lambda c: c.from_frame)[1]
    locked = apply_edit_operations(
        once,
        [op("set_clip_locked", operation_id="op_lock", clip_id=middle.clip_id, locked=True)],
    )
    again = styled(locked, B)
    assert next(c for c in again.clips if c.clip_id == middle.clip_id) == next(
        c for c in locked.clips if c.clip_id == middle.clip_id
    )


def _cards(document: EditDocumentV2) -> list[TimelineTextClip]:
    return [c for c in document.clips if isinstance(c, TimelineTextClip) and c.style_slot == "card"]


def test_cards_are_replaced_not_piled_up() -> None:
    lines = {"hook": "Kok bisa ya?", "reactions": "Serius nih?"}
    once = styled(narrated(), B, card_lines=lines)
    twice = styled(once, B, card_lines=lines)
    assert sorted(c.heading for c in _cards(twice)) == sorted(lines.values())
    assert _cards(styled(twice, A)) == []


def test_switching_styles_resets_every_look() -> None:
    def looks(document: EditDocumentV2) -> list[tuple[Any, ...]]:
        return sorted(
            (
                c.clip_id,
                c.dim,
                c.emphasis.highlight,
                c.emphasis.arrow,
                tuple(m.frame for m in c.moves),
            )
            for c in document.clips
            if isinstance(c, TimelineVideoClip) and c.position is not None
        )

    assert looks(styled(styled(narrated(), A), B)) == looks(styled(narrated(), B))
    assert looks(styled(styled(narrated(), B), A)) == looks(styled(narrated(), A))


def test_the_main_video_cuts_on_every_beats_sentence_ends() -> None:
    document = narrated()
    reactions = next(
        s
        for s in __import__(
            "thoth_control_plane.domain.story_beats", fromlist=["beat_spans"]
        ).beat_spans(document, ROLES)
        if s.beat == "reactions"
    )
    end = reactions.start_frame + 40
    after = styled(document, sentence_ends={"reactions": [end]})
    assert end in {c.from_frame for c in _main_shots(after)}


def test_a_tall_card_scrolls_in_style_a() -> None:
    data = payload()
    card = next(a for a in data["asset_refs"] if a["asset_id"] == "asset_card_a")
    card["height"] = 4000
    after = styled(narrated(data))
    cards = [
        c
        for c in after.clips
        if isinstance(c, TimelineVideoClip)
        and c.position is not None
        and c.source_role == "comment_card"
    ]
    assert cards and all(c.moves and c.moves[0].y == 0.3 for c in cards)


def test_a_short_main_video_holds_its_last_frame_under_the_style() -> None:
    # Deferred minor (2026-11-10): no restart from the first frame under later beats.
    data = payload()
    main = next(c for c in data["clips"] if c["clip_id"] == "clip_main")
    asset = next(a for a in data["asset_refs"] if a["asset_id"] == main["asset_id"])
    asset["duration_in_frames"] = 120
    main["hold_after_source"] = True
    shots = sorted(_main_shots(styled(narrated(data))), key=lambda c: c.from_frame)
    starts = [s.source_from_frame for s in shots]
    assert starts == sorted(starts)  # never back to an earlier frame
    assert shots[-1].hold_after_source


# Operator, 2026-11-10: before a paid re-voice, the beats that will only stretch are named.
def test_no_beat_is_edited_right_after_a_styled_write() -> None:
    from thoth_control_plane.domain.style_apply import edited_beats

    written = narrate_document(draft(), VOICES, [], PRESET, ROLES, style=B)
    assert edited_beats(written, ROLES) == []


def test_a_hand_edit_marks_its_beat_as_edited() -> None:
    from thoth_control_plane.domain.style_apply import edited_beats

    written = narrate_document(draft(), VOICES, [], PRESET, ROLES, style=B)
    beats = clip_beats(written, ROLES)
    shot = next(c for c in full_frame_shots(written) if beats[c.clip_id] == "main")
    edited = apply_edit_operations(written, [op("set_clip_dim", clip_id=shot.clip_id, dim=0.2)])
    assert edited_beats(edited, ROLES) == ["main"]
    assert edited_beats(draft(), ROLES) == []  # no style: nothing to compare


# Planner stage 1 (spec 2026-11-13, 5.5-5.7): planned beats place their shots, cards and credits.
CARD_PLACE = (0.0, -0.24, 0.76)


def span_of(document: EditDocumentV2, beat: str) -> tuple[int, int]:
    span = next(s for s in beat_spans(document, ROLES) if s.beat == beat)
    return span.start_frame, span.start_frame + span.duration_in_frames


def main_shot(start: int, length: int, source_from: int) -> PlannedShot:
    return PlannedShot(start, length, "asset_main", source_from, "main", False, None)


def broll_shot(start: int, length: int, credit: str | None = "@kompascomreport") -> PlannedShot:
    return PlannedShot(start, length, "asset_vid_long", 60, "broll", False, credit)


def reactions_plan(document: EditDocumentV2, *, broll: bool = True) -> BeatAssignment:
    start, end = span_of(document, "reactions")
    shots = [main_shot(start, 30, 500), main_shot(start + 30, end - start - 30, 530)]
    if broll:
        shots.append(broll_shot(start, 30))
    return BeatAssignment(
        beat="reactions",
        shots=shots,
        cards=[PlannedCard(start + 30, 30, "asset_card_a", "comment_card_001", False)],
        phrase_starts=[start, start + 20, start + 40, start + 60],
    )


def text_clips(document: EditDocumentV2, slot: str) -> list[TimelineTextClip]:
    return [c for c in document.clips if isinstance(c, TimelineTextClip) and c.style_slot == slot]


def positioned_cards(document: EditDocumentV2) -> list[TimelineVideoClip]:
    return [
        c
        for c in document.clips
        if isinstance(c, TimelineVideoClip) and c.asset_id == "asset_card_a" and c.position
    ]


def videos(document: EditDocumentV2, asset_id: str) -> list[TimelineVideoClip]:
    return [
        c for c in document.clips if isinstance(c, TimelineVideoClip) and c.asset_id == asset_id
    ]


def test_planned_beat_places_shots_cards_and_credits() -> None:
    before = narrated()
    plan = reactions_plan(before)
    start = plan.phrase_starts[0]
    after = styled(before, B, assignments={"reactions": plan})
    b_roll = [c for c in videos(after, "asset_vid_long") if c.from_frame == start]
    assert [(c.duration_in_frames, c.source_from_frame, c.position) for c in b_roll] == [
        (30, 60, None)
    ]
    credits = text_clips(after, "credit")
    assert [(c.clip_id, c.heading, c.from_frame, c.duration_in_frames) for c in credits] == [
        ("clip_style_credit_1", "@kompascomreport", start, 30)
    ]
    main_track = {t.track_id for t in after.tracks if t.kind == "main_video"}
    mains = {(c.from_frame, c.source_from_frame) for c in after.clips if c.track_id in main_track}
    assert (start, 500) in mains and (start + 30, 530) in mains
    cards = positioned_cards(after)
    assert len(cards) == len(positioned_cards(before))
    moved = next(c for c in cards if c.from_frame == start + 30)
    assert moved.duration_in_frames == 30 and moved.fit == "contain"
    assert moved.position is not None
    assert (moved.position.x, moved.position.y, moved.position.scale) == CARD_PLACE


def test_a_full_card_fills_the_screen() -> None:
    before = narrated()
    plan = reactions_plan(before)
    start = plan.phrase_starts[0]
    full = BeatAssignment(
        "reactions",
        plan.shots,
        [PlannedCard(start, 30, "asset_card_a", "comment_card_001", True)],
        plan.phrase_starts,
    )
    after = styled(before, B, assignments={"reactions": full})
    card = next(c for c in videos(after, "asset_card_a") if c.from_frame == start and not c.locked)
    assert card.position is None and card.fit == "contain"


def test_import_credits_are_replaced_but_locked_ones_stay() -> None:  # Review Focus 4
    data = payload()
    template = next(c for c in data["clips"] if c["clip_id"] == "clip_002")
    footage = next(c for c in data["clips"] if c["clip_id"] == "clip_footage_000")
    track = next(t for t in data["tracks"] if t["track_id"] == template["track_id"])
    for clip_id, locked in (("clip_credit_one", False), ("clip_credit_locked", True)):
        credit = dict(template, clip_id=clip_id, heading="@acc", body="", style_slot="credit")
        credit.update(source_role="footage", from_frame=footage["from_frame"], locked=locked)
        credit.update(duration_in_frames=20, scene_id=None)
        data["clips"].append(credit)
        track["clip_ids"].append(clip_id)
    before = narrated(data)
    start, end = span_of(before, "footage")
    plan = BeatAssignment("footage", [broll_shot(start, end - start, "@new")], [], [start])
    after = styled(before, B, assignments={"footage": plan})
    ids = {c.clip_id for c in text_clips(after, "credit")}
    assert "clip_credit_one" not in ids
    assert {"clip_credit_locked", "clip_style_credit_1"} <= ids


def test_a_locked_card_does_not_move() -> None:  # Review Focus 4
    data = payload()
    for clip in data["clips"]:
        if clip["clip_id"].startswith("clip_comment_card_"):
            clip["locked"] = True
    before = narrated(data)
    after = styled(before, B, assignments={"reactions": reactions_plan(before)})
    assert positioned_cards(after) == positioned_cards(before)


def test_card_line_sits_over_the_third_phrase_and_pushes_nothing() -> None:
    before = narrated()
    plan = reactions_plan(before)
    after = styled(
        before, B, assignments={"reactions": plan}, card_lines={"reactions": "Kok bisa?"}
    )
    cards = [c for c in text_clips(after, "card") if c.heading == "Kok bisa?"]
    assert [c.from_frame for c in cards] == [plan.phrase_starts[2]]
    assert any(c.from_frame == plan.phrase_starts[0] for c in videos(after, "asset_vid_long"))


def test_main_only_draft_has_no_broll_and_no_credits() -> None:  # Review Focus 1
    before = narrated()
    start, end = span_of(before, "reactions")
    plan = reactions_plan(before, broll=False)
    plan = BeatAssignment("reactions", plan.shots, [], plan.phrase_starts)
    after = styled(before, B, assignments={"reactions": plan})
    assert text_clips(after, "credit") == []
    b_roll = {t.track_id for t in after.tracks if t.kind == "b_roll"}
    added = [
        c
        for c in after.clips
        if c.track_id in b_roll
        and start <= c.from_frame < end
        and c.clip_id.startswith("clip_style_")
    ]
    assert added == []
