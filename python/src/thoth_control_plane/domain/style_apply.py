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
from collections.abc import Mapping, Sequence

from thoth_control_plane.domain.edit_document_v2 import (
    AppliedStyle,
    EditDocumentV2,
    TimelineCaptionClip,
    TimelineTextClip,
    TimelineVideoClip,
)
from thoth_control_plane.domain.move_presets import move_preset
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
    SetClipDim,
    SetClipEmphasis,
    SetClipHidden,
    SetClipMoves,
    SetDocumentStyle,
    SetTextPlace,
    TimelineOperation,
)


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

    def look_on(clip_id: str, duration: int, look: BeatLook, *, emphasis: bool) -> None:
        moves = move_preset(look.move, duration, fps)
        if moves:
            operations.append(
                SetClipMoves(
                    kind="set_clip_moves", operation_id=operation_id(), clip_id=clip_id, moves=moves
                )
            )
        if look.dim > 0:
            operations.append(
                SetClipDim(
                    kind="set_clip_dim", operation_id=operation_id(), clip_id=clip_id, dim=look.dim
                )
            )
        if emphasis and (look.highlight or look.arrow):
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

    for span in beat_spans(document, roles_by_item):
        look = template.beats[span.beat]
        in_beat = [clip for clip in document.clips if beats.get(clip.clip_id) == span.beat]
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
            look_on(clip.clip_id, clip.duration_in_frames, look, emphasis=True)

        line = (card_lines or {}).get(span.beat)
        between = bool(line) and span.beat != "hook" and template.cuts.card_between_facts
        placed_between = False
        by_track: dict[str, list[TimelineVideoClip]] = {}
        for clip in sorted((c for c in pictures if c.position is None), key=lambda c: c.from_frame):
            by_track.setdefault(clip.track_id, []).append(clip)
        for track_id, group in by_track.items():
            sources: list[ShotSource] = []
            role_of: dict[str, object] = {}
            fit_of: dict[str, object] = {}
            for clip in group:
                if clip.asset_id in role_of:
                    continue
                asset = refs[clip.asset_id]
                role_of[clip.asset_id] = clip.source_role or roles.get(
                    clip.clip_id.removeprefix("clip_")
                )
                fit_of[clip.asset_id] = clip.fit
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
            shots = plan_shots(
                start,
                end,
                sources,
                template.cuts,
                fps,
                (sentence_ends or {}).get(span.beat, ()),
                card_slots=1 if between and not placed_between else 0,
                card_frames=card_frames,
            )
            for shot in shots:
                if shot.source is None:
                    card(span.beat, line or "", shot.from_frame, shot.duration)
                    placed_between = True
                    continue
                asset = refs[shot.source.asset_id]
                fill = full_frame_fill(asset) if look.background == "blur_fill" else None
                scene = scenes.get(scene_id) if scene_id else None
                inside = scene is not None and (
                    scene.start_frame <= shot.from_frame
                    and shot.from_frame + shot.duration
                    <= scene.start_frame + scene.duration_in_frames
                )
                clip_id = new_clip_id(span.beat)
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
                        fit=fill[0] if fill else fit_of[shot.source.asset_id],  # type: ignore[arg-type]
                        source_role=role_of[shot.source.asset_id],  # type: ignore[arg-type]
                        background=fill[1] if fill else None,
                    )
                )
                look_on(clip_id, shot.duration, look, emphasis=False)
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
