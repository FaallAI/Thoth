"""The narrated draft: one pure change from a Studio draft and its voices (spec 2026-10-31, 5).

The narration is the spine. Beats play in story order (Hook, Main, Evidence, Reactions, Footage,
Outro); a voiced beat lasts as long as its voice (the first one also carries the lead-in), an
unvoiced beat keeps its length. Each beat's clips keep their order and relative timing inside
the new window. The main video plays under Hook through Reactions and holds its last frame if it
runs out. Narration, word-timed captions, ducking and SFX are added on top.

A narrated draft can be narrated again: the previous narration layer is recognised and replaced,
which is how one beat is re-voiced. Clip IDs derive from beats, so the result is deterministic.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass

from thoth_control_plane.domain.edit_document_v2 import (
    AssetRef,
    CaptionCue,
    CaptionWord,
    EditDocumentV2,
    TimelineAudioClip,
    TimelineCaptionClip,
    TimelineTrack,
    TimelineVideoClip,
    VolumeKeyframe,
)
from thoth_control_plane.domain.narration import BEAT_ORDER, BeatId, NarrationPreset, SfxCue
from thoth_control_plane.domain.story_beats import beat_spans, clip_beats
from thoth_control_plane.voice.ports import WordTiming

NARRATION_PREFIX = "clip_narration_"
CAPTION_PREFIX = "clip_caption_narration_"
SFX_PREFIX = "clip_sfx_"
_LAYER_PREFIXES = (NARRATION_PREFIX, CAPTION_PREFIX, SFX_PREFIX)
#: Rebuilt from the voices on every narration; SFX clips are placed once, then belong to
#: the operator like any other clip.
_REBUILT_PREFIXES = (NARRATION_PREFIX, CAPTION_PREFIX)
#: The beats the main video plays under.
BACKGROUND_BEATS: frozenset[str] = frozenset({"hook", "main", "evidence", "reactions"})
#: A beat's clips carry a role Story mode maps back to the same beat.
BEAT_ROLE: dict[str, str] = {
    "hook": "hook",
    "main": "main",
    "evidence": "post_card",
    "reactions": "comment_card",
    "footage": "footage",
    "outro": "outro",
}
EDGE_FADE_FRAMES = 2
RAMP_FRAMES = 3
PAGE_WORDS = 4
PAGE_SECONDS = 1.2
PAUSE_SECONDS = 0.3


@dataclass(frozen=True)
class VoicedBeat:
    beat: BeatId
    asset: AssetRef
    duration_seconds: float
    words: list[WordTiming]


@dataclass(frozen=True)
class PlacedSfx:
    cue: SfxCue
    asset: AssetRef
    duration_seconds: float


Window = tuple[int, int]  # [start, end)


def narrate_document(
    document: EditDocumentV2,
    voiced: Sequence[VoicedBeat],
    sfx: Sequence[PlacedSfx],
    preset: NarrationPreset,
    roles_by_item: dict[str, str] | None = None,
    *,
    place_sfx: bool | None = None,
) -> EditDocumentV2:
    """`place_sfx`: True places `sfx` and replaces earlier placed SFX (a narration, first or
    recreated); False keeps the draft's SFX as the operator left them (a re-voice). None
    places them only on a draft that has no narration yet."""
    fps = document.canvas.fps
    lead = math.ceil(preset.lead_in_seconds * fps)
    voices = {voice.beat: voice for voice in voiced}
    main_tracks = {track.track_id for track in document.tracks if track.kind == "main_video"}

    old_windows = _old_windows(document, lead, main_tracks, roles_by_item)
    beats = clip_beats(document, roles_by_item)
    narrated = any(clip.clip_id.startswith(NARRATION_PREFIX) for clip in document.clips)
    previous = {
        clip.clip_id: clip for clip in document.clips if clip.clip_id.startswith(_REBUILT_PREFIXES)
    }
    placing = (not narrated) if place_sfx is None else place_sfx
    replaced = (*_REBUILT_PREFIXES, SFX_PREFIX) if placing else _REBUILT_PREFIXES
    base = [clip for clip in document.clips if not clip.clip_id.startswith(replaced)]
    present = [beat for beat in BEAT_ORDER if beat in old_windows or beat in voices]

    new_windows: dict[str, Window] = {}
    cursor = 0
    first_voice = next((beat for beat in present if beat in voices), None)
    for beat in present:
        if beat in voices:
            length = math.ceil(voices[beat].duration_seconds * fps)
            length += lead if beat == first_voice else 0
        else:
            start, end = old_windows[beat]
            length = end - start
        new_windows[beat] = (cursor, cursor + length)
        cursor += length
    total = max(cursor, 1)
    old_total = document.canvas.duration_in_frames

    background = [beat for beat in present if beat in BACKGROUND_BEATS]
    old_bg = _union([old_windows[beat] for beat in background if beat in old_windows])
    new_bg = _union([new_windows[beat] for beat in background])
    voiced_frames = [new_windows[beat] for beat in voices if beat in new_windows]
    assets = {asset.asset_id: asset for asset in document.asset_refs}
    keep_scene = document.scenes[0]

    clips = []
    for clip in base:
        if clip.track_id in main_tracks and old_bg and new_bg:
            window = _map(clip.from_frame, clip.end_frame, old_bg, new_bg)
        elif (beat := beats.get(clip.clip_id)) in old_windows and beat in new_windows:
            window = _map(clip.from_frame, clip.end_frame, old_windows[beat], new_windows[beat])
        else:
            window = _map(clip.from_frame, clip.end_frame, (0, old_total), (0, total))
        if window[1] > total:  # an offset-mapped clip never runs past the canvas
            length = min(window[1] - window[0], total)
            window = (total - length, total)
        beat = beats.get(clip.clip_id)
        if clip.source_role is None and beat is not None:
            # The beat may come only from a scene this change removes: keep it as a role.
            clip = clip.model_copy(update={"source_role": BEAT_ROLE[beat]})
        clips.append(
            _retime(clip, window, assets, voiced_frames, keep_scene.clip_ids, first=not narrated)
        )

    tracks = {track.track_id: track for track in document.tracks}
    narration_track = _track(tracks, "narration", "Narration")
    caption_track = _track(tracks, "caption", "Captions")
    sfx_track = _track(tracks, "sfx", "SFX")

    speech: list[Window] = []
    starts: dict[str, int] = {}
    for beat in present:
        voice = voices.get(beat)
        if voice is None:
            continue
        start = new_windows[beat][0] + (lead if beat == first_voice else 0)
        length = min(
            math.ceil(voice.duration_seconds * fps),
            voice.asset.duration_in_frames or math.ceil(voice.duration_seconds * fps),
            total - start,
        )
        if length <= 0:
            continue
        starts[beat] = start
        assets[voice.asset.asset_id] = voice.asset
        role = BEAT_ROLE[beat]
        fade = EDGE_FADE_FRAMES if length >= 2 * EDGE_FADE_FRAMES else 0
        # The operator's volume and fades on a voice survive a re-voice (spec 6).
        before = previous.get(f"{NARRATION_PREFIX}{beat}")
        volume = before.volume if isinstance(before, TimelineAudioClip) else 1.0
        if isinstance(before, TimelineAudioClip):
            fade_in = min(before.fade_in_frames, length // 2)
            fade_out = min(before.fade_out_frames, length - fade_in)
        else:
            fade_in = fade_out = fade
        clips.append(
            TimelineAudioClip(
                kind="audio",
                clip_id=f"{NARRATION_PREFIX}{beat}",
                track_id=narration_track,
                from_frame=start,
                duration_in_frames=length,
                ownership="ai_managed",
                source_role=role,  # type: ignore[arg-type]
                asset_id=voice.asset.asset_id,
                volume=volume,
                fade_in_frames=fade_in,
                fade_out_frames=fade_out,
            )
        )
        caption_before = previous.get(f"{CAPTION_PREFIX}{beat}")
        same_voice = (
            isinstance(before, TimelineAudioClip)
            and before.asset_id == voice.asset.asset_id
            and isinstance(caption_before, TimelineCaptionClip)
            and caption_before.duration_in_frames == length
        )
        # An unchanged voice keeps the operator's caption fixes; a new one is paged again.
        cues = caption_before.cues if same_voice else _pages(voice.words, fps, length)  # type: ignore[union-attr]
        style = (
            caption_before.style_slot
            if isinstance(caption_before, TimelineCaptionClip)
            else "word_highlight"
        )
        if cues:
            clips.append(
                TimelineCaptionClip(
                    kind="caption",
                    clip_id=f"{CAPTION_PREFIX}{beat}",
                    track_id=caption_track,
                    from_frame=start,
                    duration_in_frames=length,
                    ownership="ai_managed",
                    source_role=role,  # type: ignore[arg-type]
                    style_slot=style,
                    cues=cues,
                )
            )
        speech.extend(_speech(voice.words, start, length, fps))

    # SFX are placed by the first narration only; afterwards they are the operator's clips.
    for index, placed in enumerate(sfx if placing else []):
        start = _sfx_start(placed.cue, starts, new_windows, voices, fps)
        if start is None or start >= total:
            continue
        length = min(
            math.ceil(placed.duration_seconds * fps),
            placed.asset.duration_in_frames or total,
            total - start,
        )
        if length <= 0:
            continue
        assets[placed.asset.asset_id] = placed.asset
        fade = EDGE_FADE_FRAMES if length >= 2 * EDGE_FADE_FRAMES else 0
        clips.append(
            TimelineAudioClip(
                kind="audio",
                clip_id=f"{SFX_PREFIX}{index}",
                track_id=sfx_track,
                from_frame=start,
                duration_in_frames=length,
                ownership="ai_managed",
                source_role=BEAT_ROLE[placed.cue.beat],  # type: ignore[arg-type]
                asset_id=placed.asset.asset_id,
                fade_in_frames=fade,
                fade_out_frames=fade,
            )
        )

    curve = _duck_curve(speech, preset, fps)
    ducked = []
    for clip in clips:
        under = (isinstance(clip, TimelineVideoClip) and clip.track_id in main_tracks) or (
            isinstance(clip, TimelineAudioClip) and not clip.clip_id.startswith(_LAYER_PREFIXES)
        )
        if under and curve:
            clip = clip.model_copy(update={"volume_keyframes": _clip_keyframes(curve, clip)})
        ducked.append(clip)

    used = {getattr(clip, "asset_id", None) for clip in ducked}
    track_clips: dict[str, list[str]] = {track_id: [] for track_id in tracks}
    for clip in ducked:
        track_clips[clip.track_id].append(clip.clip_id)
    payload = document.model_dump(mode="python")
    payload.update(
        canvas={**payload["canvas"], "duration_in_frames": total},
        scenes=[
            {
                **keep_scene.model_dump(mode="python"),
                "start_frame": 0,
                "duration_in_frames": total,
            }
        ],
        tracks=[
            {**track.model_dump(mode="python"), "clip_ids": track_clips[track.track_id]}
            for track in tracks.values()
        ],
        clips=[clip.model_dump(mode="python") for clip in ducked],
        asset_refs=[
            asset.model_dump(mode="python") for asset in assets.values() if asset.asset_id in used
        ],
    )
    return EditDocumentV2.model_validate(payload)


def _old_windows(
    document: EditDocumentV2,
    lead: int,
    main_tracks: set[str],
    roles_by_item: dict[str, str] | None,
) -> dict[str, Window]:
    """Each beat's frames before this change: Story spans, or a narrated draft's windows."""
    narration = {
        clip.clip_id.removeprefix(NARRATION_PREFIX): clip
        for clip in document.clips
        if clip.clip_id.startswith(NARRATION_PREFIX)
    }
    if not narration:
        return {
            span.beat: (span.start_frame, span.start_frame + span.duration_in_frames)
            for span in beat_spans(document, roles_by_item)
        }
    # A narrated draft laid its beats end to end; recover where each window starts.
    foreground: dict[str, list[tuple[int, int]]] = {}
    beats = clip_beats(document, roles_by_item)
    for clip in document.clips:
        beat = beats.get(clip.clip_id)
        if (
            beat
            and clip.track_id not in main_tracks
            and not clip.clip_id.startswith(_LAYER_PREFIXES)
        ):
            foreground.setdefault(beat, []).append((clip.from_frame, clip.end_frame))
    present = [
        beat
        for beat in BEAT_ORDER
        if beat in narration or beat in foreground or beat in beats.values()
    ]
    first = next(beat for beat in BEAT_ORDER if beat in narration)
    starts = {
        beat: clip.from_frame - (lead if beat == first else 0) for beat, clip in narration.items()
    }
    windows: dict[str, Window] = {}
    cursor = 0
    for index, beat in enumerate(present):
        start = starts.get(beat, cursor)
        if beat in narration:
            end = start + narration[beat].duration_in_frames + (lead if beat == first else 0)
        else:
            following = [starts[b] for b in present[index + 1 :] if b in starts]
            if following:
                end = following[0]
            elif beat in foreground:
                end = max(e for _, e in foreground[beat])
            else:
                end = start
        if end > start:
            windows[beat] = (start, end)
        cursor = max(cursor, end)
    return windows


def _union(windows: Sequence[Window]) -> Window | None:
    if not windows:
        return None
    return (min(start for start, _ in windows), max(end for _, end in windows))


def _map(start: int, end: int, old: Window, new: Window) -> Window:
    """Map a clip's frames linearly from one window onto another; at least one frame long."""
    if end <= old[0] or start >= old[1]:
        # A clip the operator moved outside its beat keeps its length and its offset.
        shifted = start + new[0] - old[0]
        return (max(shifted, 0), max(shifted, 0) + (end - start))
    old_length = max(old[1] - old[0], 1)
    ratio = (new[1] - new[0]) / old_length
    mapped_start = new[0] + math.floor((start - old[0]) * ratio)
    mapped_end = new[0] + math.floor((end - old[0]) * ratio)
    mapped_start = min(max(mapped_start, new[0]), max(new[1] - 1, new[0]))
    mapped_end = min(max(mapped_end, mapped_start + 1), max(new[1], mapped_start + 1))
    return (mapped_start, mapped_end)


def _retime(
    clip,
    window: Window,
    assets: dict[str, AssetRef],
    voiced: list[Window],
    scene_clips,
    *,
    first: bool,
):
    start, end = window
    length = end - start
    update: dict[str, object] = {
        "from_frame": start,
        "duration_in_frames": length,
        "scene_id": clip.scene_id if clip.clip_id in scene_clips else None,
    }
    if isinstance(clip, TimelineVideoClip):
        asset = assets.get(clip.asset_id)
        remaining = (
            None
            if asset is None or asset.kind != "video" or asset.duration_in_frames is None
            else asset.duration_in_frames - clip.source_from_frame
        )
        update["hold_after_source"] = remaining is not None and length > remaining
        update["volume_keyframes"] = []
        # Blur turns on with the first narration only; the operator may switch it off after.
        if first and clip.blur_regions and any(s < end and start < e for s, e in voiced):
            update["blur_enabled"] = True
    if isinstance(clip, TimelineAudioClip):
        asset = assets.get(clip.asset_id)
        if asset is not None and asset.duration_in_frames is not None:
            # Audio cannot hold a frame: a stretched clip stops where its asset ends.
            length = max(1, min(length, asset.duration_in_frames - clip.source_from_frame))
            update["duration_in_frames"] = length
        fade_in = min(clip.fade_in_frames, length // 2)
        update.update(
            fade_in_frames=fade_in,
            fade_out_frames=min(clip.fade_out_frames, length - fade_in),
            volume_keyframes=[],
        )
    if isinstance(clip, TimelineCaptionClip):
        update["cues"] = _scale_cues(clip, length)
    return clip.model_copy(update=update)


def _scale_cues(clip: TimelineCaptionClip, length: int) -> list[CaptionCue]:
    ratio = length / clip.duration_in_frames
    cues = []
    for cue in clip.cues:
        start = min(math.floor(cue.from_frame * ratio), length - 1)
        duration = max(1, min(math.floor(cue.duration_in_frames * ratio), length - start))
        cues.append(
            cue.model_copy(
                update={"from_frame": start, "duration_in_frames": duration, "words": []}
            )
        )
    return cues


def _track(tracks: dict[str, TimelineTrack], kind: str, label: str) -> str:
    existing = next((track for track in tracks.values() if track.kind == kind), None)
    if existing is not None:
        return existing.track_id
    track_id = f"track_{kind}_narration"
    order = max(track.order for track in tracks.values()) + 1
    tracks[track_id] = TimelineTrack(track_id=track_id, kind=kind, label=label, order=order)  # type: ignore[arg-type]
    return track_id


def _word_frames(word: WordTiming, fps: float, length: int) -> tuple[int, int]:
    start = min(round(word.start_seconds * fps), length - 1)
    end = min(max(round(word.end_seconds * fps), start + 1), length)
    return start, end


def _pages(words: Sequence[WordTiming], fps: float, length: int) -> list[CaptionCue]:
    """Pages of at most four words or 1.2 s, each word timed relative to its page."""
    pages: list[list[WordTiming]] = []
    for word in words:
        if not word.text.strip():
            continue
        if (
            pages
            and len(pages[-1]) < PAGE_WORDS
            and word.end_seconds - pages[-1][0].start_seconds <= PAGE_SECONDS
        ):
            pages[-1].append(word)
        else:
            pages.append([word])
    cues = []
    for index, page in enumerate(pages):
        cue_start = _word_frames(page[0], fps, length)[0]
        if cues and cue_start <= cues[-1].from_frame:
            continue
        cue_end = (
            _word_frames(pages[index + 1][0], fps, length)[0] if index + 1 < len(pages) else length
        )
        cue_end = max(cue_end, cue_start + 1)
        timed = []
        for word in page:
            start, end = _word_frames(word, fps, length)
            start = min(max(start, cue_start), cue_end - 1)
            end = min(max(end, start + 1), cue_end)
            timed.append(
                CaptionWord(
                    from_frame=start - cue_start,
                    duration_in_frames=end - start,
                    text=word.text.strip()[:300],
                )
            )
        cues.append(
            CaptionCue(
                from_frame=cue_start,
                duration_in_frames=cue_end - cue_start,
                text=" ".join(word.text for word in timed)[:300],
                words=timed,
            )
        )
    return cues


def _speech(words: Sequence[WordTiming], start: int, length: int, fps: float) -> list[Window]:
    """The frames a voice speaks in, short pauses filled."""
    pause = math.ceil(PAUSE_SECONDS * fps)
    windows: list[Window] = []
    for word in words:
        if not word.text.strip():
            continue
        begin, end = _word_frames(word, fps, length)
        window = (start + begin, start + end)
        if windows and window[0] - windows[-1][1] <= pause:
            windows[-1] = (windows[-1][0], max(windows[-1][1], window[1]))
        else:
            windows.append(window)
    return windows


def _duck_curve(
    speech: list[Window], preset: NarrationPreset, fps: float
) -> list[tuple[int, float]]:
    """Global (frame, volume) points: full, duck while speaking, leak in pauses, full after."""
    if not speech:
        return []
    pause = math.ceil(PAUSE_SECONDS * fps)
    merged: list[Window] = []
    for window in sorted(speech):
        if merged and window[0] - merged[-1][1] <= pause:
            merged[-1] = (merged[-1][0], max(merged[-1][1], window[1]))
        else:
            merged.append(window)
    points: list[tuple[int, float]] = [(0, 1.0)]

    def move(frame: int, volume: float) -> None:
        last_frame, last_volume = points[-1]
        if volume == last_volume:
            return
        hold = frame - RAMP_FRAMES
        if hold > last_frame:
            points.append((hold, last_volume))
        points.append((max(frame, points[-1][0] + 1), volume))

    for index, (start, end) in enumerate(merged):
        move(start, preset.duck_volume)
        move(end, preset.leak_volume if index + 1 < len(merged) else 1.0)
    return points


def _value_at(curve: list[tuple[int, float]], frame: int) -> float:
    frames = [point[0] for point in curve]
    index = bisect_right(frames, frame) - 1
    if index < 0:
        return curve[0][1]
    if index + 1 >= len(curve):
        return curve[-1][1]
    (f0, v0), (f1, v1) = curve[index], curve[index + 1]
    return v0 + (v1 - v0) * (frame - f0) / (f1 - f0)


def _clip_keyframes(curve: list[tuple[int, float]], clip) -> list[VolumeKeyframe]:
    start, end = clip.from_frame, clip.end_frame
    points = [(0, _value_at(curve, start))]
    points += [(frame - start, volume) for frame, volume in curve if start < frame < end]
    # One keyframe per frame at most, and never more than the field allows.
    return [VolumeKeyframe(frame=frame, volume=round(volume, 4)) for frame, volume in points][:500]


def _sfx_start(
    cue: SfxCue,
    starts: dict[str, int],
    windows: dict[str, Window],
    voices: dict[str, VoicedBeat],
    fps: float,
) -> int | None:
    if cue.beat in starts and cue.word_index is not None:
        words = [word for word in voices[cue.beat].words if word.text.strip()]
        if cue.word_index < len(words):
            return starts[cue.beat] + round(words[cue.word_index].start_seconds * fps)
    if cue.beat in starts:
        return starts[cue.beat]
    window = windows.get(cue.beat)
    return window[0] if window else None
