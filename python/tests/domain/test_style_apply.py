"""Applying a style: a draft's cuts and look rebuilt from its materials (spec 2026-11-10, 6)."""

from __future__ import annotations

from typing import Any

from tests.assembly.test_narration_timeline import PRESET, ROLES, VOICES, draft, payload
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
