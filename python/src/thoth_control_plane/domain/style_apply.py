"""Applying a style: a draft's cuts and look rebuilt from its own materials (spec 2026-11-10, 6).

The result is ordinary typed edit operations, so a style is one revision and one undo step:

- in each Story beat, the visible, unlocked full-frame picture clips are removed and placed again
  as shots (`plan_shots`), each with the beat's move, dim and blur-fill;
- a beat's positioned cards keep their place and take the beat's move, dim and emphasis;
- a beat's heading text takes the beat's place, and every caption the style's caption style;
- a card line becomes a `card` text clip: at the hook's start, elsewhere between facts;
- locked or hidden clips, narration, music, SFX and clips with no beat are never touched.
"""

from __future__ import annotations

import itertools
import logging
import re
from collections.abc import Mapping, Sequence

from thoth_control_plane.domain.edit_document_v2 import (
    AppliedStyle,
    EditDocumentV2,
    TimelineCaptionClip,
    TimelineTextClip,
    TimelineVideoClip,
)
from thoth_control_plane.domain.move_presets import MovePreset, move_preset
from thoth_control_plane.domain.narration import BeatId
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
STYLE_CARD = re.compile(r"clip_style_[a-z]+_card_\d+")
#: How much taller than the canvas a picture must be to take a beat's tall move.
TALL_TOLERANCE = 0.05


def style_operations(
    document: EditDocumentV2,
    template: StyleTemplate,
    roles_by_item: Mapping[str, str] | None = None,
    sentence_ends: Mapping[BeatId, Sequence[int]] | None = None,
    card_lines: Mapping[BeatId, str] | None = None,
) -> list[TimelineOperation]:
    """The operations that put `document` in `template`'s style, the style record last."""
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

    # The last style's cards go first: a new style, or a re-voice, places its own.
    old_cards = {
        clip.clip_id
        for clip in document.clips
        if isinstance(clip, TimelineTextClip)
        and STYLE_CARD.fullmatch(clip.clip_id)
        and not clip.locked
    }
    operations.extend(
        RemoveClip(kind="remove_clip", operation_id=operation_id(), clip_id=clip_id)
        for clip_id in sorted(old_cards)
    )
    taken -= old_cards
    # Every beat's sentence ends: the main video runs under several beats.
    all_ends = sorted({frame for ends in (sentence_ends or {}).values() for frame in ends})
    tracks = {track.track_id: track for track in document.tracks}

    for span in beat_spans(document, roles_by_item):
        look = template.beats[span.beat]
        in_beat = [
            clip
            for clip in document.clips
            if beats.get(clip.clip_id) == span.beat and clip.clip_id not in old_cards
        ]
        pictures = [
            clip
            for clip in in_beat
            if isinstance(clip, TimelineVideoClip) and not clip.hidden and not clip.locked
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
        between = (
            bool(line)
            and span.beat != "hook"
            and template.cuts.card_between_facts
            and text_track is not None
        )
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
            kept = sorted(
                (c.from_frame, c.from_frame + c.duration_in_frames)
                for c in document.clips
                if c.track_id == track_id
                and c.clip_id not in group_ids
                and c.clip_id not in old_cards
                and (main_track or beats.get(c.clip_id) == span.beat)
                and c.from_frame < end
                and start < c.from_frame + c.duration_in_frames
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
                    source_clip = first[shot.source.asset_id]
                    asset = refs[shot.source.asset_id]
                    fill = full_frame_fill(asset) if look.background == "blur_fill" else None
                    scene = scenes.get(scene_id) if scene_id else None
                    inside = scene is not None and (
                        scene.start_frame <= shot.from_frame
                        and shot.from_frame + shot.duration
                        <= scene.start_frame + scene.duration_in_frames
                    )
                    clip_id = new_clip_id(span.beat)
                    blurred = source_clip.blur_enabled or bool(source_clip.blur_regions)
                    operations.append(
                        AddClipFromAsset(
                            kind="add_clip_from_asset",
                            operation_id=operation_id(),
                            clip_id=clip_id,
                            track_id=track_id,
                            asset_id=shot.source.asset_id,
                            from_frame=shot.from_frame,
                            duration_in_frames=shot.duration,
                            source_from_frame=shot.source_from_frame,
                            scene_id=scene_id if inside else None,
                            fit=fill[0] if fill else source_clip.fit,
                            source_role=source_clip.source_role
                            or roles.get(source_clip.clip_id.removeprefix("clip_")),  # type: ignore[arg-type]
                            background=fill[1] if fill else None,
                            # The subtitle blur sits in source frames, so every shot keeps it.
                            blur_enabled=source_clip.blur_enabled if blurred else None,
                            blur_regions=list(source_clip.blur_regions) if blurred else None,
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
                    look_on(clip_id, shot.source.asset_id, shot.duration, look, card=False)
        if line and not placed_between:
            card(span.beat, line, span.start_frame, min(card_frames, span.duration_in_frames))

        if look.heading_place is not None:
            operations.extend(
                SetTextPlace(
                    kind="set_text_place",
                    operation_id=operation_id(),
                    clip_id=clip.clip_id,
                    style_slot=look.heading_place,
                )
                for clip in in_beat
                if isinstance(clip, TimelineTextClip) and not clip.locked
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
            style=AppliedStyle(template_id=template.template_id, revision=template.revision),
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
