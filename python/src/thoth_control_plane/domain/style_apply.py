"""Applying a style: a draft's cuts and look rebuilt from its own materials (spec 2026-11-10, 6).

The result is ordinary typed edit operations, so a style is one revision and one undo step:

- in each Story beat, the visible, unlocked full-frame picture clips are removed and placed again
  as shots (`plan_shots`), each with the beat's move, dim and blur-fill;
- a beat's positioned cards keep their place and take the beat's move, dim and emphasis;
- a beat's heading text takes the beat's place, and every caption the style's caption style;
- a card line becomes a `card` text clip: at the hook's start, elsewhere between facts;
- a planned beat (planner stage 1, spec 2026-11-13) places the planner's shots, cards and credits:
  the main video's shots on its track, footage on the b-roll with a credit, a card moved to the
  phrase that names it; the cursor fills only what the plan leaves open;
- locked or hidden clips, narration, music, SFX and clips with no beat are never touched.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import replace

from thoth_control_plane.domain.edit_document_v2 import (
    AppliedStyle,
    EditDocumentV2,
    Position,
    TimelineCaptionClip,
    TimelineTextClip,
    TimelineVideoClip,
)
from thoth_control_plane.domain.move_presets import MovePreset, move_preset
from thoth_control_plane.domain.narration import BEAT_ORDER, BeatId
from thoth_control_plane.domain.planner_assign import BeatAssignment, PlannedCard, PlannedShot
from thoth_control_plane.domain.story_beats import beat_spans, clip_beats
from thoth_control_plane.domain.studio_layout import full_frame_fill
from thoth_control_plane.domain.style_cuts import ShotSource, plan_shots
from thoth_control_plane.domain.style_templates import BeatLook, StyleTemplate
from thoth_control_plane.domain.timeline_operations import (
    AddClipFromAsset,
    AddTextClip,
    RemoveClip,
    SetCaptionStyle,
    SetClipCrop,
    SetClipDim,
    SetClipEmphasis,
    SetClipHidden,
    SetClipMoves,
    SetDocumentStyle,
    SetTextPlace,
    TimelineOperation,
)

logger = logging.getLogger(__name__)
#: A style's card line clip, removed when a style or a re-voice places its own.
STYLE_CARD = re.compile(r"clip_style_([a-z]+)_card_\d+")
#: How much taller than the canvas a picture must be to take a beat's tall move.
TALL_TOLERANCE = 0.05
#: A clip the planner placed (a footage shot, a card, a credit), named for its beat: it is
#: removed only when that beat is planned again, and never cut as the cursor's material.
PLANNER_CLIP = re.compile(r"clip_style_([a-z]+)_(?:plan|credit)_\d+")
#: Where the import places a card over the picture; a planned overlay card sits there too.
CARD_POSITION = Position(x=0.0, y=-0.24, scale=0.76)
#: A planned clip carries its beat's role, so Story mode keeps it in that beat.
_BEAT_ROLE = {
    "hook": "hook",
    "main": "main",
    "evidence": "post_card",
    "reactions": "comment_card",
    "footage": "footage",
    "outro": "outro",
}


def style_operations(
    document: EditDocumentV2,
    template: StyleTemplate,
    roles_by_item: Mapping[str, str] | None = None,
    sentence_ends: Mapping[BeatId, Sequence[int]] | None = None,
    card_lines: Mapping[BeatId, str] | None = None,
    recut: set[str] | None = None,
    card_at: Mapping[BeatId, int] | None = None,
    assignments: Mapping[BeatId, BeatAssignment] | None = None,
) -> list[TimelineOperation]:
    """The operations that put `document` in `template`'s style, the style record last.
    `recut` limits the cuts to those beats (a re-voice, operator 2026-11-10). `card_at` is the
    frame the voice says a beat's card line: its card shows there instead of between facts.
    `assignments` are the planner's beats (spec 2026-11-13): their shots, cards and credits."""
    fps = document.canvas.fps
    roles = roles_by_item or {}
    beats = clip_beats(document, roles_by_item)
    refs = {ref.asset_id: ref for ref in document.asset_refs}
    scenes = {scene.scene_id: scene for scene in document.scenes}
    taken = {clip.clip_id for clip in document.clips}
    text_track = next((t.track_id for t in document.tracks if t.kind == "overlay"), None)
    card_frames = max(1, round(template.narration.card_seconds * fps))
    numbers = itertools.count(1)
    operations: list[TimelineOperation] = []

    def operation_id() -> str:
        return f"op_style_{next(numbers)}"

    def new_clip_id(beat: str) -> str:
        for index in itertools.count(1):
            candidate = f"clip_style_{beat}_{index}"
            if candidate not in taken:
                taken.add(candidate)
                return candidate
        raise AssertionError("unreachable")

    def moved(asset_id: str, look: BeatLook) -> MovePreset:
        """A picture taller than the canvas takes the beat's tall move, when it has one."""
        asset = refs.get(asset_id)
        canvas_ratio = document.canvas.height / document.canvas.width
        tall = bool(
            asset is not None
            and asset.width
            and asset.height
            and asset.height / asset.width > canvas_ratio + TALL_TOLERANCE
        )
        return look.tall_move if tall and look.tall_move is not None else look.move

    def look_on(clip_id: str, asset_id: str, duration: int, look: BeatLook, *, card: bool) -> None:
        moves = move_preset(moved(asset_id, look), duration, fps)
        # A kept card takes absolute values, so a switch leaves nothing of the last style.
        if moves or card:
            operations.append(
                SetClipMoves(
                    kind="set_clip_moves", operation_id=operation_id(), clip_id=clip_id, moves=moves
                )
            )
        if look.dim > 0 or card:
            operations.append(
                SetClipDim(
                    kind="set_clip_dim", operation_id=operation_id(), clip_id=clip_id, dim=look.dim
                )
            )
        if card:
            operations.append(
                SetClipEmphasis(
                    kind="set_clip_emphasis",
                    operation_id=operation_id(),
                    clip_id=clip_id,
                    highlight=look.highlight,
                    arrow=look.arrow,
                )
            )

    def card(beat: BeatId, text: str, start: int, duration: int) -> None:
        if text_track is None:
            return
        operations.append(
            AddTextClip(
                kind="add_text_clip",
                operation_id=operation_id(),
                clip_id=new_clip_id(f"{beat}_card"),
                track_id=text_track,
                from_frame=start,
                duration_in_frames=max(1, duration),
                heading=text,
                body="",
                style_slot="card",
                source_role=beat if beat in ("hook", "outro") else None,  # type: ignore[arg-type]
            )
        )

    def place(
        beat: str,
        track_id: str,
        asset_id: str,
        start: int,
        duration: int,
        source_from: int,
        hold: bool,
        source_clip: TimelineVideoClip,
        scene_id: str | None,
        look: BeatLook,
    ) -> None:
        """One shot of a material already in the beat: the cursor's, or the planner's."""
        asset = refs[asset_id]
        fill = full_frame_fill(asset) if look.background == "blur_fill" else None
        scene = scenes.get(scene_id) if scene_id else None
        inside = scene is not None and (
            scene.start_frame <= start
            and start + duration <= scene.start_frame + scene.duration_in_frames
        )
        clip_id = new_clip_id(beat)
        blurred = source_clip.blur_enabled or bool(source_clip.blur_regions)
        operations.append(
            AddClipFromAsset(
                kind="add_clip_from_asset",
                operation_id=operation_id(),
                clip_id=clip_id,
                track_id=track_id,
                asset_id=asset_id,
                from_frame=start,
                duration_in_frames=duration,
                source_from_frame=source_from,
                scene_id=scene_id if inside else None,
                fit=fill[0] if fill else (look.fit or source_clip.fit),
                source_role=source_clip.source_role
                or roles.get(source_clip.clip_id.removeprefix("clip_")),  # type: ignore[arg-type]
                background=fill[1] if fill else None,
                # The subtitle blur sits in source frames, so every shot keeps it.
                blur_enabled=source_clip.blur_enabled if blurred else None,
                blur_regions=list(source_clip.blur_regions) if blurred else None,
                hold_after_source=True if hold else None,
            )
        )
        if source_clip.crop is not None:
            operations.append(
                SetClipCrop(
                    kind="set_clip_crop",
                    operation_id=operation_id(),
                    clip_id=clip_id,
                    crop=source_clip.crop,
                )
            )
        look_on(clip_id, asset_id, duration, look, card=False)

    def planned_broll(beat: BeatId, track_id: str, shot: PlannedShot, look: BeatLook) -> None:
        """A planned footage shot over the main video, with its source's credit."""
        asset = refs.get(shot.asset_id)
        fill = (
            full_frame_fill(asset) if asset is not None and look.background == "blur_fill" else None
        )
        clip_id = new_clip_id(f"{beat}_plan")
        operations.append(
            AddClipFromAsset(
                kind="add_clip_from_asset",
                operation_id=operation_id(),
                clip_id=clip_id,
                track_id=track_id,
                asset_id=shot.asset_id,
                from_frame=shot.from_frame,
                duration_in_frames=shot.duration,
                source_from_frame=shot.source_from_frame,
                fit=fill[0] if fill else (look.fit or "cover"),
                source_role=_BEAT_ROLE[beat],  # type: ignore[arg-type]
                background=fill[1] if fill else None,
                hold_after_source=True if shot.hold else None,
            )
        )
        look_on(clip_id, shot.asset_id, shot.duration, look, card=False)
        if shot.credit and text_track is not None:
            operations.append(
                AddTextClip(
                    kind="add_text_clip",
                    operation_id=operation_id(),
                    clip_id=new_clip_id(f"{beat}_credit"),
                    track_id=text_track,
                    from_frame=shot.from_frame,
                    duration_in_frames=shot.duration,
                    heading=shot.credit,
                    body="",
                    style_slot="credit",
                )
            )

    def planned_card_clip(
        beat: BeatId, track_id: str, planned_card: PlannedCard, look: BeatLook
    ) -> None:
        """A card over the phrase that names it; a card with no base fills the screen."""
        clip_id = new_clip_id(f"{beat}_plan")
        operations.append(
            AddClipFromAsset(
                kind="add_clip_from_asset",
                operation_id=operation_id(),
                clip_id=clip_id,
                track_id=track_id,
                asset_id=planned_card.asset_id,
                from_frame=planned_card.from_frame,
                duration_in_frames=planned_card.duration,
                fit="contain",
                position=None if planned_card.full else CARD_POSITION,
                source_role=_BEAT_ROLE[beat],  # type: ignore[arg-type]
            )
        )
        look_on(clip_id, planned_card.asset_id, planned_card.duration, look, card=True)

    # The last style's cards go first: a new style, or a re-voice, places its own.
    old_cards = {
        clip.clip_id
        for clip in document.clips
        if isinstance(clip, TimelineTextClip)
        and (style_card := STYLE_CARD.fullmatch(clip.clip_id))
        and (recut is None or style_card.group(1) in recut)
        and not clip.locked
    }
    operations.extend(
        RemoveClip(kind="remove_clip", operation_id=operation_id(), clip_id=clip_id)
        for clip_id in sorted(old_cards)
    )
    taken -= old_cards
    planned = {
        beat: plan for beat, plan in (assignments or {}).items() if recut is None or beat in recut
    }
    # The main video runs under several beats as one cut: every beat's planned main shots
    # go back when it is cut, a re-voiced beat's or not (final review, 2026-11-13).
    planned_main = sorted(
        (
            shot
            for plan in (assignments or {}).values()
            for shot in plan.shots
            if shot.layer == "main"
        ),
        key=lambda shot: shot.from_frame,
    )
    b_roll_track = next((t.track_id for t in document.tracks if t.kind == "b_roll"), None)

    def planner_beat(clip_id: str) -> str | None:
        found = PLANNER_CLIP.fullmatch(clip_id)
        return found.group(1) if found else None

    # A beat planned again first loses what the planner placed there before; the import's
    # per-scene footage credits make way for one credit per footage shot; a locked clip stays.
    gone = {
        clip.clip_id
        for clip in document.clips
        if not clip.locked
        and (
            planner_beat(clip.clip_id) in planned
            or (
                isinstance(clip, TimelineTextClip)
                and beats.get(clip.clip_id) in planned
                and (clip.source_role or roles.get(clip.clip_id.removeprefix("clip_"))) == "footage"
                and clip.heading.startswith("@")
                and not clip.body.strip()
            )
        )
    }
    # A planned card moves: the import's unlocked placement of that card is taken away first.
    movable = [
        clip
        for clip in document.clips
        if isinstance(clip, TimelineVideoClip)
        and clip.position is not None
        and clip.clip_id not in old_cards
    ]
    placed_cards: list[tuple[BeatId, PlannedCard, bool]] = []
    for beat, plan in planned.items():
        if b_roll_track is None or not template.beats[beat].use:
            continue  # nowhere to show it: the card stays where it is
        for planned_card in plan.cards:
            same = [
                c for c in movable if c.asset_id == planned_card.asset_id and c.clip_id not in gone
            ]
            free = next((c for c in same if not c.locked), None)
            if same and free is None:
                continue  # only locked placements of this card: it stays where the operator put it
            if free is not None:
                gone.add(free.clip_id)
            placed_cards.append((beat, planned_card, free is not None))
    operations.extend(
        RemoveClip(kind="remove_clip", operation_id=operation_id(), clip_id=clip_id)
        for clip_id in sorted(gone)
    )
    taken -= gone
    # Every beat's sentence ends: the main video runs under several beats.
    all_ends = sorted({frame for ends in (sentence_ends or {}).values() for frame in ends})
    tracks = {track.track_id: track for track in document.tracks}

    for span in beat_spans(document, roles_by_item):
        if recut is not None and span.beat not in recut:
            continue
        look = template.beats[span.beat]
        in_beat = [
            clip
            for clip in document.clips
            if beats.get(clip.clip_id) == span.beat
            and clip.clip_id not in old_cards
            and clip.clip_id not in gone
        ]
        # What the planner placed is never the cursor's material: it stays as it is until its
        # beat is planned again (final review, 2026-11-13).
        pictures = [
            clip
            for clip in in_beat
            if isinstance(clip, TimelineVideoClip)
            and not clip.hidden
            and not clip.locked
            and planner_beat(clip.clip_id) is None
        ]
        if not look.use:
            operations.extend(
                SetClipHidden(
                    kind="set_clip_hidden",
                    operation_id=operation_id(),
                    clip_id=c.clip_id,
                    hidden=True,
                )
                for c in pictures
            )
            continue
        for clip in (c for c in pictures if c.position is not None):
            look_on(clip.clip_id, clip.asset_id, clip.duration_in_frames, look, card=True)

        line = (card_lines or {}).get(span.beat)
        spoken = None if span.beat == "hook" else (card_at or {}).get(span.beat)
        between = (
            bool(line)
            and spoken is None
            and span.beat != "hook"
            and template.cuts.card_between_facts
            and not template.cuts.planned
            and text_track is not None
        )
        plan = planned.get(span.beat)
        if plan is not None:
            for shot in (s for s in plan.shots if s.layer == "broll"):
                if b_roll_track is not None:
                    planned_broll(span.beat, b_roll_track, shot, look)
            for beat_of, planned_card, _ in placed_cards:
                if beat_of == span.beat and b_roll_track is not None:
                    planned_card_clip(span.beat, b_roll_track, planned_card, look)
        placed_between = False
        by_track: dict[str, list[TimelineVideoClip]] = {}
        for clip in sorted((c for c in pictures if c.position is None), key=lambda c: c.from_frame):
            by_track.setdefault(clip.track_id, []).append(clip)
        for track_id, group in by_track.items():
            track = tracks[track_id]
            if track.locked:
                logger.warning("style skips a locked track track=%s beat=%s", track_id, span.beat)
                continue
            sources: list[ShotSource] = []
            first: dict[str, TimelineVideoClip] = {}
            for clip in group:
                if clip.asset_id in first:
                    continue
                asset = refs[clip.asset_id]
                first[clip.asset_id] = clip
                sources.append(
                    ShotSource(
                        asset_id=clip.asset_id,
                        kind="image" if asset.kind == "image" else "video",
                        source_from_frame=clip.source_from_frame,
                        source_frames=asset.duration_in_frames if asset.kind == "video" else None,
                    )
                )
            start = min(c.from_frame for c in group)
            end = max(c.from_frame + c.duration_in_frames for c in group)
            scene_id = group[0].scene_id
            operations.extend(
                RemoveClip(kind="remove_clip", operation_id=operation_id(), clip_id=c.clip_id)
                for c in group
            )
            # Kept clips (hidden or locked here, anything on a main track) are built around.
            group_ids = {c.clip_id for c in group}
            main_track = track.kind == "main_video"
            kept = [
                (c.from_frame, c.from_frame + c.duration_in_frames)
                for c in document.clips
                if c.track_id == track_id
                and c.clip_id not in group_ids
                and c.clip_id not in old_cards
                and c.clip_id not in gone
                and (main_track or beats.get(c.clip_id) == span.beat)
                and c.from_frame < end
                and start < c.from_frame + c.duration_in_frames
            ]
            # The planner's shots are placed as they are; the cursor fills only what is left.
            own_plan: list[PlannedShot] = []
            if main_track:
                # A main shot never overlaps a kept piece of the main video (a locked one): it
                # is trimmed to the free stretches, as the cursor's shots are.
                free = _free_windows(start, end, sorted(kept))
                own_plan = [
                    replace(
                        shot,
                        from_frame=a,
                        duration=b - a,
                        source_from_frame=shot.source_from_frame + (a - shot.from_frame),
                    )
                    for shot in planned_main
                    for window_start, window_end in free
                    if (a := max(shot.from_frame, window_start))
                    < (b := min(shot.from_frame + shot.duration, window_end))
                ]
            elif plan is not None and track_id == b_roll_track:
                own_plan = [s for s in plan.shots if s.layer == "broll"]
            kept = sorted(kept + [(s.from_frame, s.from_frame + s.duration) for s in own_plan])
            if main_track:
                for shot in own_plan:
                    place(
                        span.beat,
                        track_id,
                        shot.asset_id,
                        shot.from_frame,
                        shot.duration,
                        shot.source_from_frame,
                        shot.hold,
                        group[0],
                        scene_id,
                        look,
                    )
            for window_start, window_end in _free_windows(start, end, kept):
                window_sources = sources
                if len(sources) == 1 and sources[0].kind == "video":
                    # One movie keeps its own timing across a gap, as it played before.
                    only = sources[0]
                    window_sources = [
                        ShotSource(
                            asset_id=only.asset_id,
                            kind=only.kind,
                            source_from_frame=only.source_from_frame + (window_start - start),
                            source_frames=only.source_frames,
                        )
                    ]
                shots = plan_shots(
                    window_start,
                    window_end,
                    window_sources,
                    template.cuts,
                    fps,
                    all_ends,
                    card_slots=1 if between and not placed_between else 0,
                    card_frames=card_frames,
                )
                for shot in shots:
                    if shot.source is None:
                        card(span.beat, line or "", shot.from_frame, shot.duration)
                        placed_between = True
                        continue
                    place(
                        span.beat,
                        track_id,
                        shot.source.asset_id,
                        shot.from_frame,
                        shot.duration,
                        shot.source_from_frame,
                        shot.hold,
                        first[shot.source.asset_id],
                        scene_id,
                        look,
                    )
        if line and not placed_between:
            length = min(card_frames, span.duration_in_frames)
            end = span.start_frame + span.duration_in_frames
            at = span.start_frame
            if spoken is not None:
                at = max(span.start_frame, min(spoken, end - length))
            elif template.cuts.planned and span.beat != "hook":
                # Over the third phrase (or the last of a shorter beat), never in a slot of its
                # own: the phrase windows stay on the voice (spec 2026-11-13, 5.7).
                starts = (
                    plan.phrase_starts
                    if plan is not None
                    else sorted(
                        f
                        for f in (sentence_ends or {}).get(span.beat, ())
                        if span.start_frame <= f < end
                    )
                )
                if starts:
                    at = max(span.start_frame, min(starts[min(2, len(starts) - 1)], end - length))
            card(span.beat, line, at, length)

        if look.heading_place is not None:
            operations.extend(
                SetTextPlace(
                    kind="set_text_place",
                    operation_id=operation_id(),
                    clip_id=clip.clip_id,
                    style_slot=look.heading_place,
                )
                for clip in in_beat
                # A credit keeps its corner: it is no heading (2026-11-12).
                if isinstance(clip, TimelineTextClip)
                and not clip.locked
                and clip.style_slot != "credit"
            )

    operations.extend(
        SetCaptionStyle(
            kind="set_caption_style",
            operation_id=operation_id(),
            clip_id=clip.clip_id,
            style_slot=template.captions.style,
        )
        for clip in document.clips
        if isinstance(clip, TimelineCaptionClip) and not clip.locked
    )
    operations.append(
        SetDocumentStyle(
            kind="set_document_style",
            operation_id=operation_id(),
            # Cut from a voice's timing: the draft is not cut by the style again on a re-voice.
            style=AppliedStyle(
                template_id=template.template_id,
                revision=template.revision,
                voiced=sentence_ends is not None,
            ),
        )
    )
    return operations


def _free_windows(start: int, end: int, kept: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """[start, end) less the kept clips' ranges: the stretches a style may fill."""
    windows: list[tuple[int, int]] = []
    cursor = start
    for begin, stop in kept:
        if begin > cursor:
            windows.append((cursor, min(begin, end)))
        cursor = max(cursor, stop)
    if cursor < end:
        windows.append((cursor, end))
    return [(a, b) for a, b in windows if b > a]


def beat_fingerprints(
    document: EditDocumentV2, roles_by_item: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Per beat, a fingerprint of its picture and text clips: any hand edit changes it."""
    beats = clip_beats(document, roles_by_item)
    grouped: dict[str, list[dict[str, object]]] = {}
    for clip in sorted(document.clips, key=lambda c: c.clip_id):
        beat = beats.get(clip.clip_id)
        if beat is not None and isinstance(clip, (TimelineVideoClip, TimelineTextClip)):
            grouped.setdefault(beat, []).append(clip.model_dump(mode="json"))
    return {
        beat: hashlib.sha256(json.dumps(clips, sort_keys=True).encode()).hexdigest()[:32]
        for beat, clips in grouped.items()
    }


def edited_beats(
    document: EditDocumentV2, roles_by_item: Mapping[str, str] | None = None
) -> list[BeatId]:
    """Beats whose shots changed since the last narration write: a re-voice only stretches
    them, which the operator sees before paying for it (operator, 2026-11-10)."""
    style = document.style
    if style is None or not style.voiced or not style.cuts:
        return []
    now = beat_fingerprints(document, roles_by_item)
    return [
        beat
        for beat in BEAT_ORDER
        if (beat in now or beat in style.cuts) and now.get(beat) != style.cuts.get(beat)
    ]
