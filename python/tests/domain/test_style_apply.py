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
from thoth_control_plane.domain.story_beats import clip_beats
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
