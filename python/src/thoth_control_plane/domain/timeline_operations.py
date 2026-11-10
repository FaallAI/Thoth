"""Pure, typed timeline operations for version 2 edit documents.

Every operation mutates a caller-owned working copy in place. The caller is
responsible for revalidating the document once the whole ordered batch has
been applied, which is what makes a batch atomic: a rejection anywhere leaves
the caller's original document untouched.

Operations never accept an artifact locator. ``add_clip_from_asset`` names an
asset by identity only and copies the safe projection the repository resolved
for the owning project.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import Field

from thoth_control_plane.domain.clip_moves import shift_moves, split_moves
from thoth_control_plane.domain.edit_document_v2 import (
    TRACK_CLIP_KINDS,
    AppliedStyle,
    AssetRef,
    Background,
    CaptionCue,
    CaptionStyle,
    ClipBlurRegion,
    Crop,
    Dim,
    EditDocumentV2,
    Emphasis,
    FadeFrames,
    FitMode,
    Mark,
    Motion,
    MoveKeyframes,
    PlaybackSpeed,
    Position,
    StoryRole,
    TimelineAudioClip,
    TimelineCaptionClip,
    TimelineClip,
    TimelineMarker,
    TimelineTextClip,
    TimelineTrack,
    TimelineVideoClip,
    TrackKind,
    Volume,
    speed_percent,
)
from thoth_control_plane.domain.edit_documents import (
    BodyText,
    Frame,
    FrameStart,
    ShortText,
    StyleSlot,
)
from thoth_control_plane.domain.models import OpaqueId, StrictModel


class AddTrack(StrictModel):
    kind: Literal["add_track"]
    operation_id: OpaqueId
    track_id: OpaqueId
    track_kind: TrackKind
    label: Annotated[str, Field(min_length=1, max_length=120)]
    order: Annotated[int, Field(ge=0)]


class RemoveEmptyTrack(StrictModel):
    kind: Literal["remove_empty_track"]
    operation_id: OpaqueId
    track_id: OpaqueId


class ReorderTrack(StrictModel):
    kind: Literal["reorder_track"]
    operation_id: OpaqueId
    track_id: OpaqueId
    order: Annotated[int, Field(ge=0)]


class AddClipFromAsset(StrictModel):
    kind: Literal["add_clip_from_asset"]
    operation_id: OpaqueId
    clip_id: OpaqueId
    track_id: OpaqueId
    asset_id: OpaqueId
    from_frame: FrameStart
    duration_in_frames: Frame
    source_from_frame: FrameStart = 0
    #: Binds the clip to a scene, so it moves with the scene and stays inside it.
    scene_id: OpaqueId | None = None
    #: A card keeps its framing and placement from the moment it is added (Story mode).
    fit: FitMode | None = None
    position: Position | None = None
    source_role: StoryRole | None = None
    #: Blur-fill for full-frame media of another shape (spec 2026-11-09, 3.8).
    background: Background | None = Field(default=None, exclude_if=lambda value: value is None)
    #: A style's shot keeps its source clip's subtitle blur, in source frames (spec 2026-11-10).
    blur_enabled: bool | None = Field(default=None, exclude_if=lambda value: value is None)
    blur_regions: Annotated[list[ClipBlurRegion], Field(max_length=20)] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class ReorderScene(StrictModel):
    kind: Literal["reorder_scene"]
    operation_id: OpaqueId
    scene_id: OpaqueId
    to_index: Annotated[int, Field(ge=0)]


class RemoveClip(StrictModel):
    kind: Literal["remove_clip"]
    operation_id: OpaqueId
    clip_id: OpaqueId


class MoveClip(StrictModel):
    kind: Literal["move_clip"]
    operation_id: OpaqueId
    clip_id: OpaqueId
    target_track_id: OpaqueId
    from_frame: FrameStart
    ripple: bool = False


class TrimClipStart(StrictModel):
    kind: Literal["trim_clip_start"]
    operation_id: OpaqueId
    clip_id: OpaqueId
    from_frame: FrameStart


class TrimClipEnd(StrictModel):
    kind: Literal["trim_clip_end"]
    operation_id: OpaqueId
    clip_id: OpaqueId
    end_frame: Frame


class SplitClip(StrictModel):
    kind: Literal["split_clip"]
    operation_id: OpaqueId
    clip_id: OpaqueId
    split_frame: FrameStart
    left_clip_id: OpaqueId
    right_clip_id: OpaqueId


class SetClipHidden(StrictModel):
    kind: Literal["set_clip_hidden"]
    operation_id: OpaqueId
    clip_id: OpaqueId
    hidden: bool


class SetClipLocked(StrictModel):
    kind: Literal["set_clip_locked"]
    operation_id: OpaqueId
    clip_id: OpaqueId
    locked: bool


class SetClipVolume(StrictModel):
    kind: Literal["set_clip_volume"]
    operation_id: OpaqueId
    clip_id: OpaqueId
    volume: Volume


class SetClipBlur(StrictModel):
    kind: Literal["set_clip_blur"]
    operation_id: OpaqueId
    clip_id: OpaqueId
    blur_enabled: bool


class SetCaptionCueText(StrictModel):
    kind: Literal["set_caption_cue_text"]
    operation_id: OpaqueId
    clip_id: OpaqueId
    cue_index: Annotated[int, Field(ge=0)]
    text: ShortText


class AddCaptionClip(StrictModel):
    """A caption with one cue across the whole clip: its scene, or a stretch of it when given."""

    kind: Literal["add_caption_clip"]
    operation_id: OpaqueId
    clip_id: OpaqueId
    track_id: OpaqueId
    scene_id: OpaqueId
    text: ShortText
    #: Left out when unused, so an operation without them reads exactly as it always did.
    from_frame: FrameStart | None = Field(default=None, exclude_if=lambda value: value is None)
    duration_in_frames: Frame | None = Field(default=None, exclude_if=lambda value: value is None)


class SetCaptionCueTiming(StrictModel):
    """Cue frames are relative to the start of the caption clip."""

    kind: Literal["set_caption_cue_timing"]
    operation_id: OpaqueId
    clip_id: OpaqueId
    cue_index: Annotated[int, Field(ge=0)]
    from_frame: FrameStart
    duration_in_frames: Frame


class SetCaptionStyle(StrictModel):
    kind: Literal["set_caption_style"]
    operation_id: OpaqueId
    clip_id: OpaqueId
    style_slot: CaptionStyle


class SetTextPlace(StrictModel):
    """Where a text clip's heading sits on the canvas; `title` is the middle, as it always was."""

    kind: Literal["set_text_place"]
    operation_id: OpaqueId
    clip_id: OpaqueId
    style_slot: Literal["title_top", "title", "title_lower", "card"]


class SetClipPosition(StrictModel):
    kind: Literal["set_clip_position"]
    operation_id: OpaqueId
    clip_id: OpaqueId
    position: Position


class SetClipMotion(StrictModel):
    kind: Literal["set_clip_motion"]
    operation_id: OpaqueId
    clip_id: OpaqueId
    motion: Motion


class SetClipEmphasis(StrictModel):
    kind: Literal["set_clip_emphasis"]
    operation_id: OpaqueId
    clip_id: OpaqueId
    highlight: bool
    arrow: bool


class SetClipMoves(StrictModel):
    """The whole keyframe list: a preset, a removed keyframe and a clear are each one step."""

    kind: Literal["set_clip_moves"]
    operation_id: OpaqueId
    clip_id: OpaqueId
    moves: MoveKeyframes


class SetClipBackground(StrictModel):
    kind: Literal["set_clip_background"]
    operation_id: OpaqueId
    clip_id: OpaqueId
    background: Background


class SetDocumentStyle(StrictModel):
    """Record (or clear) the style template a draft took (spec 2026-11-10)."""

    kind: Literal["set_document_style"]
    operation_id: OpaqueId
    style: AppliedStyle | None


class SetClipDim(StrictModel):
    kind: Literal["set_clip_dim"]
    operation_id: OpaqueId
    clip_id: OpaqueId
    dim: Dim


class SetClipMarks(StrictModel):
    kind: Literal["set_clip_marks"]
    operation_id: OpaqueId
    clip_id: OpaqueId
    marks: Annotated[list[Mark], Field(max_length=12)]


class ReplaceClipAsset(StrictModel):
    """Swap the media behind a clip; its timing, framing and Story styling stay."""

    kind: Literal["replace_clip_asset"]
    operation_id: OpaqueId
    clip_id: OpaqueId
    asset_id: OpaqueId


class AddTextClip(StrictModel):
    """A Hook or Outro text over the overlay track, bound to no scene (Story mode, spec 8)."""

    kind: Literal["add_text_clip"]
    operation_id: OpaqueId
    clip_id: OpaqueId
    track_id: OpaqueId
    from_frame: FrameStart
    duration_in_frames: Frame
    heading: ShortText
    body: BodyText
    style_slot: StyleSlot
    #: None for a text pasted onto the timeline (spec 2026-11-08 section 6), not a Story beat.
    source_role: Literal["hook", "outro"] | None = None


class DuplicateClip(StrictModel):
    """Copy a clip under a new id; its media, provenance and styling stay, its scene does not."""

    kind: Literal["duplicate_clip"]
    operation_id: OpaqueId
    clip_id: OpaqueId
    new_clip_id: OpaqueId
    track_id: OpaqueId
    from_frame: FrameStart


class SetClipFit(StrictModel):
    kind: Literal["set_clip_fit"]
    operation_id: OpaqueId
    clip_id: OpaqueId
    fit: FitMode


class SetClipCrop(StrictModel):
    """None restores the whole source frame."""

    kind: Literal["set_clip_crop"]
    operation_id: OpaqueId
    clip_id: OpaqueId
    crop: Crop | None = None


class SetClipFades(StrictModel):
    """Fades on a video or audio clip; their sum must fit inside the clip."""

    kind: Literal["set_clip_fades"]
    operation_id: OpaqueId
    clip_id: OpaqueId
    fade_in_frames: FadeFrames
    fade_out_frames: FadeFrames


class SetClipSpeed(StrictModel):
    """A video or audio clip's speed; its place and length stay (Tier 3a)."""

    kind: Literal["set_clip_speed"]
    operation_id: OpaqueId
    clip_id: OpaqueId
    speed: PlaybackSpeed


class SlipClip(StrictModel):
    """Move the content inside a video or audio clip; the clip keeps its place (Tier 3a)."""

    kind: Literal["slip_clip"]
    operation_id: OpaqueId
    clip_id: OpaqueId
    source_from_frame: FrameStart


MarkerLabel = Annotated[str, Field(max_length=60)]


class AddMarker(StrictModel):
    kind: Literal["add_marker"]
    operation_id: OpaqueId
    marker_id: OpaqueId
    frame: FrameStart
    label: MarkerLabel = ""


class SetMarker(StrictModel):
    kind: Literal["set_marker"]
    operation_id: OpaqueId
    marker_id: OpaqueId
    frame: FrameStart
    label: MarkerLabel


class RemoveMarker(StrictModel):
    kind: Literal["remove_marker"]
    operation_id: OpaqueId
    marker_id: OpaqueId


class SetTrackVisibility(StrictModel):
    kind: Literal["set_track_visibility"]
    operation_id: OpaqueId
    track_id: OpaqueId
    hidden: bool


class SetTrackMuted(StrictModel):
    kind: Literal["set_track_muted"]
    operation_id: OpaqueId
    track_id: OpaqueId
    muted: bool


class SetTrackLocked(StrictModel):
    kind: Literal["set_track_locked"]
    operation_id: OpaqueId
    track_id: OpaqueId
    locked: bool


TimelineOperation: TypeAlias = Annotated[
    AddTrack
    | RemoveEmptyTrack
    | ReorderTrack
    | ReorderScene
    | AddClipFromAsset
    | RemoveClip
    | MoveClip
    | TrimClipStart
    | TrimClipEnd
    | SplitClip
    | SetClipHidden
    | SetClipLocked
    | SetClipVolume
    | SetClipBlur
    | SetCaptionCueText
    | AddCaptionClip
    | SetCaptionCueTiming
    | SetCaptionStyle
    | SetTextPlace
    | SetClipPosition
    | SetClipMotion
    | SetClipEmphasis
    | SetClipMoves
    | SetClipBackground
    | SetClipDim
    | SetDocumentStyle
    | SetClipMarks
    | ReplaceClipAsset
    | AddTextClip
    | DuplicateClip
    | SetClipFit
    | SetClipCrop
    | SetClipFades
    | SetClipSpeed
    | SlipClip
    | AddMarker
    | SetMarker
    | RemoveMarker
    | SetTrackVisibility
    | SetTrackMuted
    | SetTrackLocked,
    Field(discriminator="kind"),
]


def apply_timeline_operation(
    document: EditDocumentV2,
    operation: TimelineOperation,
    resolved_assets: dict[str, AssetRef],
) -> None:
    """Apply one timeline operation to ``document`` in place."""
    match operation:
        case AddTrack():
            _add_track(document, operation)
        case RemoveEmptyTrack():
            _remove_empty_track(document, operation)
        case ReorderTrack():
            _unlocked_track(document, operation.track_id).order = operation.order
        case ReorderScene():
            _reorder_scene(document, operation)
        case AddClipFromAsset():
            _add_clip_from_asset(document, operation, resolved_assets)
        case RemoveClip():
            _remove_clip(document, operation)
        case MoveClip():
            _move_clip(document, operation)
        case TrimClipStart():
            _trim_clip_start(document, operation)
        case TrimClipEnd():
            _trim_clip_end(document, operation)
        case SplitClip():
            _split_clip(document, operation)
        case SetClipHidden():
            _unlocked_clip(document, operation.clip_id).hidden = operation.hidden
        case SetClipLocked():
            _clip(document, operation.clip_id).locked = operation.locked
        case SetClipVolume():
            _set_clip_volume(document, operation)
        case SetClipBlur():
            clip = _unlocked_clip(document, operation.clip_id)
            if not isinstance(clip, TimelineVideoClip):
                raise ValueError("blur applies only to video clips")
            clip.blur_enabled = operation.blur_enabled
        case SetCaptionCueText():
            clip = _unlocked_clip(document, operation.clip_id)
            if not isinstance(clip, TimelineCaptionClip) or operation.cue_index >= len(clip.cues):
                raise ValueError("caption cue unavailable")
            clip.cues[operation.cue_index].text = operation.text
        case AddCaptionClip():
            _add_caption_clip(document, operation)
        case SetCaptionCueTiming():
            _set_caption_cue_timing(document, operation)
        case SetCaptionStyle():
            clip = _unlocked_clip(document, operation.clip_id)
            if not isinstance(clip, TimelineCaptionClip):
                raise ValueError("caption style applies only to caption clips")
            clip.style_slot = operation.style_slot
        case SetTextPlace():
            clip = _unlocked_clip(document, operation.clip_id)
            if not isinstance(clip, TimelineTextClip):
                raise ValueError("text place applies only to text clips")
            clip.style_slot = operation.style_slot
        case SetClipPosition():
            _unlocked_video_clip(document, operation.clip_id).position = operation.position
        case SetClipMotion():
            _unlocked_video_clip(document, operation.clip_id).motion = operation.motion
        case SetClipEmphasis():
            clip = _unlocked_video_clip(document, operation.clip_id)
            # The two whole-clip switches leave the clip's marks as they are (spec 2026-11-09).
            clip.emphasis = Emphasis(
                highlight=operation.highlight, arrow=operation.arrow, marks=clip.emphasis.marks
            )
        case SetClipMoves():
            clip = _unlocked_video_clip(document, operation.clip_id)
            frames = [move.frame for move in operation.moves]
            # Refused, not fitted: the person asked for these frames (fitting is for later edits).
            if frames and (frames != sorted(set(frames)) or frames[-1] >= clip.duration_in_frames):
                raise ValueError("moves must be increasing and inside the clip")
            clip.moves = list(operation.moves)
        case SetClipBackground():
            clip = _unlocked_video_clip(document, operation.clip_id)
            clip.background = operation.background
            if operation.background == "blur_fill":
                # A covering picture leaves no room to see the blur (spec 2026-11-09, 3.2).
                clip.fit = "contain"
        case SetClipDim():
            _unlocked_video_clip(document, operation.clip_id).dim = operation.dim
        case SetDocumentStyle():
            document.style = operation.style
        case SetClipMarks():
            clip = _unlocked_video_clip(document, operation.clip_id)
            clip.emphasis = clip.emphasis.model_copy(update={"marks": list(operation.marks)})
        case ReplaceClipAsset():
            _replace_clip_asset(document, operation, resolved_assets)
        case AddTextClip():
            _add_text_clip(document, operation)
        case DuplicateClip():
            _duplicate_clip(document, operation)
        case SetClipFit():
            _unlocked_video_clip(document, operation.clip_id).fit = operation.fit
        case SetClipCrop():
            _unlocked_video_clip(document, operation.clip_id).crop = operation.crop
        case SetClipFades():
            _set_clip_fades(document, operation)
        case SetClipSpeed():
            _set_clip_speed(document, operation)
        case SlipClip():
            _slip_clip(document, operation)
        case AddMarker():
            if any(marker.marker_id == operation.marker_id for marker in document.markers):
                raise ValueError("operation reuses an existing marker ID")
            document.markers.append(
                TimelineMarker(
                    marker_id=operation.marker_id, frame=operation.frame, label=operation.label
                )
            )
        case SetMarker():
            marker = _marker(document, operation.marker_id)
            marker.frame = operation.frame
            marker.label = operation.label
        case RemoveMarker():
            document.markers.remove(_marker(document, operation.marker_id))
        case SetTrackVisibility():
            _unlocked_track(document, operation.track_id).hidden = operation.hidden
        case SetTrackMuted():
            _unlocked_track(document, operation.track_id).muted = operation.muted
        case SetTrackLocked():
            _track(document, operation.track_id).locked = operation.locked


# --------------------------------------------------------------------------
# Lookup and lock gates
# --------------------------------------------------------------------------


def _track(document: EditDocumentV2, track_id: str) -> TimelineTrack:
    for track in document.tracks:
        if track.track_id == track_id:
            return track
    raise ValueError("operation references an unknown track")


def _clip(document: EditDocumentV2, clip_id: str) -> TimelineClip:
    for clip in document.clips:
        if clip.clip_id == clip_id:
            return clip
    raise ValueError("operation references an unknown clip")


def _unlocked_track(document: EditDocumentV2, track_id: str) -> TimelineTrack:
    track = _track(document, track_id)
    if track.locked:
        raise ValueError("track is locked")
    return track


def _unlocked_clip(document: EditDocumentV2, clip_id: str) -> TimelineClip:
    clip = _clip(document, clip_id)
    if clip.locked:
        raise ValueError("clip is locked")
    _unlocked_track(document, clip.track_id)
    return clip


def unlocked_clip(document: EditDocumentV2, clip_id: str) -> TimelineClip:
    """The clip, refused when it or its track is locked (shared with the scene operations)."""
    return _unlocked_clip(document, clip_id)


def _unlocked_video_clip(document: EditDocumentV2, clip_id: str) -> TimelineVideoClip:
    clip = _unlocked_clip(document, clip_id)
    if not isinstance(clip, TimelineVideoClip):
        raise ValueError("operation applies only to video clips")
    return clip


# --------------------------------------------------------------------------
# Scene strip
# --------------------------------------------------------------------------


def carry_scene_clips(
    document: EditDocumentV2, previous_starts: dict[str, int], skip: frozenset[str] = frozenset()
) -> None:
    """Keep every scene-bound clip at its offset after the scene strip is laid out again.

    A clip that no longer fits a shortened scene is trimmed at its end.
    """
    scenes = {scene.scene_id: scene for scene in document.scenes}
    for clip in document.clips:
        scene = scenes.get(clip.scene_id or "")
        if scene is None or clip.clip_id in skip:
            continue
        clip.from_frame += scene.start_frame - previous_starts[scene.scene_id]
        clip.duration_in_frames = min(
            clip.duration_in_frames, scene.start_frame + scene.duration_in_frames - clip.from_frame
        )
        if isinstance(clip, TimelineCaptionClip):
            # Cues are relative to the clip, so a trimmed caption pulls its cues in.
            for cue in clip.cues:
                cue.from_frame = min(cue.from_frame, clip.duration_in_frames - 1)
                cue.duration_in_frames = min(
                    cue.duration_in_frames, clip.duration_in_frames - cue.from_frame
                )


def _add_caption_clip(document: EditDocumentV2, operation: AddCaptionClip) -> None:
    track = _unlocked_track(document, operation.track_id)
    scene = next((s for s in document.scenes if s.scene_id == operation.scene_id), None)
    if scene is None:
        raise ValueError("operation references an unknown scene")
    if any(clip.clip_id == operation.clip_id for clip in document.clips):
        raise ValueError("operation reuses an existing clip ID")
    if "caption" not in TRACK_CLIP_KINDS[track.kind]:
        raise ValueError("clip kind is incompatible with track")

    duration = operation.duration_in_frames or scene.duration_in_frames
    document.clips.append(
        TimelineCaptionClip(
            kind="caption",
            clip_id=operation.clip_id,
            track_id=track.track_id,
            scene_id=scene.scene_id,
            from_frame=scene.start_frame if operation.from_frame is None else operation.from_frame,
            duration_in_frames=duration,
            ownership="user_edited",
            style_slot="caption_default",
            cues=[CaptionCue(from_frame=0, duration_in_frames=duration, text=operation.text)],
        )
    )
    track.clip_ids.append(operation.clip_id)


def _set_caption_cue_timing(document: EditDocumentV2, operation: SetCaptionCueTiming) -> None:
    clip = _unlocked_clip(document, operation.clip_id)
    if not isinstance(clip, TimelineCaptionClip) or operation.cue_index >= len(clip.cues):
        raise ValueError("caption cue unavailable")
    if operation.from_frame + operation.duration_in_frames > clip.duration_in_frames:
        raise ValueError("caption cues must stay inside their clip")
    cue = clip.cues[operation.cue_index]
    cue.from_frame = operation.from_frame
    cue.duration_in_frames = operation.duration_in_frames


def _reorder_scene(document: EditDocumentV2, operation: ReorderScene) -> None:
    moving = next(
        (scene for scene in document.scenes if scene.scene_id == operation.scene_id), None
    )
    if moving is None:
        raise ValueError("operation references an unknown scene")
    if operation.to_index >= len(document.scenes):
        raise ValueError("scene index is out of range")

    previous_starts = {scene.scene_id: scene.start_frame for scene in document.scenes}
    document.scenes.remove(moving)
    document.scenes.insert(operation.to_index, moving)
    start_frame = 0
    for scene in document.scenes:
        scene.start_frame = start_frame
        start_frame += scene.duration_in_frames
    starts = {scene.scene_id: scene.start_frame for scene in document.scenes}
    for clip in document.clips:
        if clip.scene_id in starts and starts[clip.scene_id] != previous_starts[clip.scene_id]:
            _unlocked_clip(document, clip.clip_id)
    carry_scene_clips(document, previous_starts)


# --------------------------------------------------------------------------
# Track lifecycle
# --------------------------------------------------------------------------


def _add_track(document: EditDocumentV2, operation: AddTrack) -> None:
    if any(track.track_id == operation.track_id for track in document.tracks):
        raise ValueError("operation reuses an existing track ID")
    document.tracks.append(
        TimelineTrack(
            track_id=operation.track_id,
            kind=operation.track_kind,
            label=operation.label,
            order=operation.order,
        )
    )


def _remove_empty_track(document: EditDocumentV2, operation: RemoveEmptyTrack) -> None:
    track = _unlocked_track(document, operation.track_id)
    if track.clip_ids:
        raise ValueError("only an empty track can be removed")
    document.tracks.remove(track)


# --------------------------------------------------------------------------
# Clip lifecycle
# --------------------------------------------------------------------------


def _add_clip_from_asset(
    document: EditDocumentV2,
    operation: AddClipFromAsset,
    resolved_assets: dict[str, AssetRef],
) -> None:
    track = _unlocked_track(document, operation.track_id)
    if any(clip.clip_id == operation.clip_id for clip in document.clips):
        raise ValueError("operation reuses an existing clip ID")

    asset = _usable_asset(document, operation.asset_id, resolved_assets)

    fields = {
        "clip_id": operation.clip_id,
        "track_id": track.track_id,
        "scene_id": operation.scene_id,
        "from_frame": operation.from_frame,
        "duration_in_frames": operation.duration_in_frames,
        "ownership": "user_edited",
        "asset_id": asset.asset_id,
        "source_from_frame": operation.source_from_frame,
    }
    clip: TimelineClip
    if asset.kind == "audio":
        clip = TimelineAudioClip(kind="audio", **fields)
    else:
        layout: dict[str, object] = {"fit": operation.fit} if operation.fit is not None else {}
        if operation.background is not None:
            layout["background"] = operation.background
        if operation.blur_enabled is not None:
            layout["blur_enabled"] = operation.blur_enabled
        if operation.blur_regions is not None:
            layout["blur_regions"] = [region.model_copy() for region in operation.blur_regions]
        clip = TimelineVideoClip(kind="video", position=operation.position, **layout, **fields)
    clip.source_role = operation.source_role
    document.clips.append(clip)
    track.clip_ids.append(clip.clip_id)


def _usable_asset(
    document: EditDocumentV2, asset_id: str, resolved_assets: dict[str, AssetRef]
) -> AssetRef:
    """The project's ready asset, recorded in the document's references."""
    asset = resolved_assets.get(asset_id)
    if asset is None:
        raise ValueError("operation references an unavailable asset")
    if asset.project_id != document.project_id:
        raise ValueError("asset belongs to another project")
    if asset.validation_state != "ready":
        raise ValueError("asset is not ready for use")
    if all(known.asset_id != asset.asset_id for known in document.asset_refs):
        document.asset_refs.append(asset.model_copy(deep=True))
    return asset


def _replace_clip_asset(
    document: EditDocumentV2,
    operation: ReplaceClipAsset,
    resolved_assets: dict[str, AssetRef],
) -> None:
    clip = _unlocked_video_clip(document, operation.clip_id)
    current = next(ref for ref in document.asset_refs if ref.asset_id == clip.asset_id)
    asset = resolved_assets.get(operation.asset_id)
    if asset is None or asset.kind != current.kind:
        raise ValueError("a clip's media is replaced only by an asset of the same kind")
    _usable_asset(document, operation.asset_id, resolved_assets)
    if asset.kind == "video":
        if asset.duration_in_frames is None:
            raise ValueError("video asset duration is unknown")
        # Only this clip shortens; its neighbours keep their frames. The speed stays (Tier 3a).
        fits = asset.duration_in_frames * 100 // speed_percent(clip)
        clip.duration_in_frames = max(1, min(clip.duration_in_frames, fits))
    clip.asset_id = asset.asset_id
    clip.source_from_frame = 0
    # Crop and blur regions are fractions and frames of the old medium; they do not carry over.
    clip.crop = None
    clip.blur_regions = []
    clip.blur_enabled = False
    # Marks point at the old medium's content, so they go with it (spec 2026-11-09, 3.4).
    clip.emphasis = clip.emphasis.model_copy(update={"marks": []})
    clip.ownership = "user_edited"


def _add_text_clip(document: EditDocumentV2, operation: AddTextClip) -> None:
    track = _unlocked_track(document, operation.track_id)
    if track.kind != "overlay":
        raise ValueError("text clips go on an overlay track")
    if any(clip.clip_id == operation.clip_id for clip in document.clips):
        raise ValueError("operation reuses an existing clip ID")
    document.clips.append(
        TimelineTextClip(
            kind="text",
            clip_id=operation.clip_id,
            track_id=track.track_id,
            from_frame=operation.from_frame,
            duration_in_frames=operation.duration_in_frames,
            ownership="user_edited",
            heading=operation.heading,
            body=operation.body,
            style_slot=operation.style_slot,
            source_role=operation.source_role,
        )
    )
    track.clip_ids.append(operation.clip_id)


def _remove_clip(document: EditDocumentV2, operation: RemoveClip) -> None:
    clip = _unlocked_clip(document, operation.clip_id)
    document.clips.remove(clip)
    _track(document, clip.track_id).clip_ids.remove(clip.clip_id)


def _move_clip(document: EditDocumentV2, operation: MoveClip) -> None:
    clip = _unlocked_clip(document, operation.clip_id)
    target = _unlocked_track(document, operation.target_track_id)

    if target.track_id != clip.track_id:
        _track(document, clip.track_id).clip_ids.remove(clip.clip_id)
        target.clip_ids.append(clip.clip_id)
        clip.track_id = target.track_id
    clip.from_frame = operation.from_frame

    if operation.ripple:
        _repack(document, target, clip.clip_id)


def _repack(document: EditDocumentV2, track: TimelineTrack, moved_clip_id: str) -> None:
    """Close gaps and overlaps on ``track``, letting the moved clip claim its slot."""
    clips = [clip for clip in document.clips if clip.track_id == track.track_id]
    clips.sort(key=lambda clip: (clip.from_frame, clip.clip_id != moved_clip_id))
    start = min(clip.from_frame for clip in clips)
    for clip in clips:
        clip.from_frame = start
        start += clip.duration_in_frames


# --------------------------------------------------------------------------
# Timing
# --------------------------------------------------------------------------


def _trim_clip_start(document: EditDocumentV2, operation: TrimClipStart) -> None:
    clip = _unlocked_clip(document, operation.clip_id)
    end_frame = clip.end_frame
    if operation.from_frame >= end_frame:
        raise ValueError("trim must leave a positive duration")

    delta = operation.from_frame - clip.from_frame
    source_from_frame = getattr(clip, "source_from_frame", None)
    if source_from_frame is not None:
        # A faster clip spends its source faster (Tier 3a); offsets round down on both sides.
        moved = delta * speed_percent(clip) // 100
        if source_from_frame + moved < 0:
            raise ValueError("trim cannot start before the source")
        clip.source_from_frame = source_from_frame + moved
    if isinstance(clip, TimelineVideoClip):
        # Moves are relative to the start: the picture at the new start stays as it was.
        clip.moves = shift_moves(clip.moves, delta)
    clip.from_frame = operation.from_frame
    clip.duration_in_frames = end_frame - operation.from_frame


def _trim_clip_end(document: EditDocumentV2, operation: TrimClipEnd) -> None:
    clip = _unlocked_clip(document, operation.clip_id)
    if operation.end_frame <= clip.from_frame:
        raise ValueError("trim must leave a positive duration")
    clip.duration_in_frames = operation.end_frame - clip.from_frame


def _split_clip(document: EditDocumentV2, operation: SplitClip) -> None:
    clip = _unlocked_clip(document, operation.clip_id)
    if not clip.from_frame < operation.split_frame < clip.end_frame:
        raise ValueError("split frame must fall inside the clip")
    if operation.left_clip_id == operation.right_clip_id:
        raise ValueError("split requires two distinct new clip IDs")

    taken = {other.clip_id for other in document.clips if other is not clip}
    if taken & {operation.left_clip_id, operation.right_clip_id}:
        raise ValueError("operation reuses an existing clip ID")

    end_frame = clip.end_frame
    left_duration = operation.split_frame - clip.from_frame
    right = clip.model_copy(deep=True)
    right.clip_id = operation.right_clip_id
    right.from_frame = operation.split_frame
    right.duration_in_frames = end_frame - operation.split_frame
    if getattr(right, "source_from_frame", None) is not None:
        right.source_from_frame += left_duration * speed_percent(clip) // 100

    track = _track(document, clip.track_id)
    track.clip_ids[track.clip_ids.index(clip.clip_id)] = operation.left_clip_id
    track.clip_ids.append(right.clip_id)
    clip.clip_id = operation.left_clip_id
    clip.duration_in_frames = left_duration
    if isinstance(clip, TimelineAudioClip | TimelineVideoClip):
        # The cut sits between the two parts: neither fades there.
        clip.fade_out_frames = 0
        right.fade_in_frames = 0
    if isinstance(clip, TimelineVideoClip) and isinstance(right, TimelineVideoClip):
        clip.moves, right.moves = split_moves(clip.moves, left_duration)
    document.clips.append(right)


def _duplicate_clip(document: EditDocumentV2, operation: DuplicateClip) -> None:
    clip = _clip(document, operation.clip_id)
    track = _unlocked_track(document, operation.track_id)
    if any(other.clip_id == operation.new_clip_id for other in document.clips):
        raise ValueError("operation reuses an existing clip ID")
    if clip.kind not in TRACK_CLIP_KINDS[track.kind]:
        raise ValueError("clip kind is incompatible with track")
    copy = clip.model_copy(deep=True)
    copy.clip_id = operation.new_clip_id
    copy.track_id = track.track_id
    copy.from_frame = operation.from_frame
    copy.scene_id = None
    # A copy is footage, not a second Hook or Outro (operator, 2026-11-09).
    copy.source_role = None
    copy.locked = False
    document.clips.append(copy)
    track.clip_ids.append(copy.clip_id)


def _set_clip_fades(document: EditDocumentV2, operation: SetClipFades) -> None:
    clip = _unlocked_clip(document, operation.clip_id)
    if not isinstance(clip, TimelineAudioClip | TimelineVideoClip):
        raise ValueError("fades apply only to video and audio clips")
    if operation.fade_in_frames + operation.fade_out_frames > clip.duration_in_frames:
        raise ValueError("fades must stay inside their clip")
    clip.fade_in_frames = operation.fade_in_frames
    clip.fade_out_frames = operation.fade_out_frames


def _set_clip_speed(document: EditDocumentV2, operation: SetClipSpeed) -> None:
    clip = _unlocked_clip(document, operation.clip_id)
    if not isinstance(clip, TimelineAudioClip | TimelineVideoClip):
        raise ValueError("speed applies only to video and audio clips")
    asset = next((ref for ref in document.asset_refs if ref.asset_id == clip.asset_id), None)
    if asset is not None and asset.kind == "image":
        raise ValueError("an image has no speed")
    clip.speed = operation.speed
    clip.ownership = "user_edited"


def _slip_clip(document: EditDocumentV2, operation: SlipClip) -> None:
    clip = _unlocked_clip(document, operation.clip_id)
    if not isinstance(clip, TimelineAudioClip | TimelineVideoClip):
        raise ValueError("slip applies only to video and audio clips")
    asset = next((ref for ref in document.asset_refs if ref.asset_id == clip.asset_id), None)
    if asset is not None and asset.kind == "image":
        raise ValueError("an image has no source time")
    # Validation skips held clips, so a held clip's start is checked here (final review 2026-11-09).
    held = isinstance(clip, TimelineVideoClip) and clip.hold_after_source
    length = asset.duration_in_frames if asset is not None else None
    if held and length is not None and operation.source_from_frame >= length:
        raise ValueError("a held clip must start inside its source")
    # The document's validation refuses a start whose span runs past the source.
    clip.source_from_frame = operation.source_from_frame
    clip.ownership = "user_edited"


def _marker(document: EditDocumentV2, marker_id: str) -> TimelineMarker:
    marker = next((entry for entry in document.markers if entry.marker_id == marker_id), None)
    if marker is None:
        raise ValueError("operation references an unknown marker")
    return marker


def fit_markers(document: EditDocumentV2) -> None:
    """Move every marker past a shortened document's end onto its last frame."""
    last = document.canvas.duration_in_frames - 1
    for marker in document.markers:
        marker.frame = min(marker.frame, last)


def fit_fades(document: EditDocumentV2) -> None:
    """Shrink fades a shorter clip can no longer hold: the fade out first, then the fade in."""
    for clip in document.clips:
        if not isinstance(clip, TimelineAudioClip | TimelineVideoClip):
            continue
        clip.fade_in_frames = min(clip.fade_in_frames, clip.duration_in_frames)
        clip.fade_out_frames = min(
            clip.fade_out_frames, clip.duration_in_frames - clip.fade_in_frames
        )


def _set_clip_volume(document: EditDocumentV2, operation: SetClipVolume) -> None:
    clip = _unlocked_clip(document, operation.clip_id)
    if not isinstance(clip, TimelineAudioClip):
        raise ValueError("volume applies only to audio clips")
    clip.volume = operation.volume
