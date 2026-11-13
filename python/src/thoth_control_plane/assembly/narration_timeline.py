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
import re
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise

from thoth_control_plane.domain.clip_moves import stretch_moves
from thoth_control_plane.domain.edit_document_operations import apply_edit_operations
from thoth_control_plane.domain.edit_document_v2 import (
    AssetRef,
    CaptionCue,
    CaptionWord,
    EditDocumentV2,
    TimelineAudioClip,
    TimelineCaptionClip,
    TimelineTextClip,
    TimelineTrack,
    TimelineVideoClip,
    VolumeKeyframe,
    frames_left,
)
from thoth_control_plane.domain.narration import BEAT_ORDER, BeatId, NarrationPreset, SfxCue
from thoth_control_plane.domain.planner import DraftPlan, split_phrases
from thoth_control_plane.domain.planner_assign import BeatAssignment, assign_beat
from thoth_control_plane.domain.story_beats import beat_spans, clip_beats
from thoth_control_plane.domain.style_apply import beat_fingerprints, style_operations
from thoth_control_plane.domain.style_templates import StyleTemplate
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
    intro_frames: int = 0,
    style: StyleTemplate | None = None,
    card_lines: Mapping[BeatId, str] | None = None,
    headline: str | None = None,
    plan: DraftPlan | None = None,
) -> EditDocumentV2:
    """`place_sfx`: True places `sfx` and replaces earlier placed SFX (a narration, first or
    recreated); False keeps the draft's SFX as the operator left them (a re-voice). None
    places them only on a draft that has no narration yet. `headline`, the script's, becomes
    the main title unless a person wrote that title (operator, 2026-11-12)."""
    if headline:
        document = _with_headline(document, roles_by_item, headline)
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
    if not narrated and intro_frames > 0:
        # The first narration opens on the scene after the source's own title card (operator,
        # 2026-11-08). A re-voice keeps where the operator left the main video.
        base = [
            clip.model_copy(update={"source_from_frame": intro_frames})
            if isinstance(clip, TimelineVideoClip)
            and clip.track_id in main_tracks
            and clip.from_frame == 0
            and clip.source_from_frame < intro_frames
            else clip
            for clip in base
        ]
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

    # The first narration lays each beat's clips on a track end to end over the beat's window: an
    # imported draft layers cards over the main video with gaps, and mapping that span linearly
    # shrank cards to flashes. A narrated draft's layout is the operator's, so it maps linearly.
    packed: dict[str, Window] = {}
    if not narrated:
        # The main video runs to the end of its beats: mapped over a span the cards made longer
        # than it, it stopped early and left black behind them.
        main_clips = [clip for clip in base if clip.track_id in main_tracks]
        old_bg = _union([(clip.from_frame, clip.end_frame) for clip in main_clips]) or old_bg
        groups: dict[tuple[str, str], list] = {}
        for clip in base:
            beat = beats.get(clip.clip_id)
            if clip.track_id in main_tracks or clip.hidden or beat not in new_windows:
                continue
            old = old_windows.get(beat)
            if old is not None and old[0] < clip.end_frame and clip.from_frame < old[1]:
                groups.setdefault((beat, clip.track_id), []).append(clip)
        for (beat, _), members in groups.items():
            packed.update(_pack(members, new_windows[beat]))

    clips = []
    for clip in base:
        if clip.track_id in main_tracks and old_bg and new_bg:
            window = _map(clip.from_frame, clip.end_frame, old_bg, new_bg)
        elif clip.clip_id in packed:
            window = packed[clip.clip_id]
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
        page_words = style.captions.words_per_caption if style is not None else PAGE_WORDS
        cues = (
            caption_before.cues  # type: ignore[union-attr]
            if same_voice
            else _pages(voice.words, fps, length, page_words)
        )
        caption_style = (
            caption_before.style_slot
            if isinstance(caption_before, TimelineCaptionClip)
            else style.captions.style
            if style is not None
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
                    style_slot=caption_style,
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
        # Every movie with sound ducks, footage on the b-roll too (stage1, 2026-11-12).
        under = _sounding(clip, assets) or (
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
        # A shorter voice-over keeps every marker on the draft (Tier 3a).
        markers=[
            {**marker.model_dump(mode="python"), "frame": min(marker.frame, total - 1)}
            for marker in document.markers
        ],
    )
    narrated_document = EditDocumentV2.model_validate(payload)
    applied = narrated_document.style
    if style is None:
        return narrated_document
    only: set[str] | None = None
    kept: list[str] = []
    if applied is not None and applied.voiced:
        # A re-voice re-cuts a beat whose voice changed only when its shots are as the last
        # write left them; a beat with hand edits only stretches (operator, 2026-11-10).
        changed = [
            beat
            for beat, voice in voices.items()
            if not (
                isinstance(old := previous.get(f"{NARRATION_PREFIX}{beat}"), TimelineAudioClip)
                and old.asset_id == voice.asset.asset_id
            )
        ]
        before = beat_fingerprints(document, roles_by_item)
        only = {b for b in changed if b in applied.cuts and applied.cuts[b] == before.get(b)}
        kept = [b for b in changed if b not in only]
        if not only:
            return _recorded(narrated_document, roles_by_item, kept)
    assignments: dict[BeatId, BeatAssignment] | None = None
    if style.cuts.planned:
        # Planner stage 1 (spec 2026-11-13): cut on phrase starts; a plan picks each picture.
        windows = {
            beat: _phrase_windows(voices[beat].words, start, new_windows[beat], fps)  # type: ignore[index]
            for beat, start in starts.items()
        }
        ends = {beat: [a for a, _ in phrases] for beat, phrases in windows.items()}
        if plan is not None:
            assignments = _assignments(plan, narrated_document, voices, windows, fps)
            assets.update({ref.asset_id: ref for ref in plan.assets})
    else:
        # The draft's style cuts its beats on the voice's sentence ends (spec 2026-11-10, 6).
        ends = {
            beat: sentence_ends(voices[beat].words, start, fps)  # type: ignore[index]
            for beat, start in starts.items()
        }
    # A card shows while the voice says its line, when it says it.
    card_at = {
        beat: frame
        for beat, line in (card_lines or {}).items()
        if beat in starts
        and (frame := spoken_at(line, voices[beat].words, starts[beat], fps)) is not None
    }
    operations = style_operations(
        narrated_document,
        style,
        roles_by_item,
        ends,
        card_lines,
        recut=only,
        card_at=card_at,
        assignments=assignments,
    )
    resolved = {asset.asset_id: asset for asset in narrated_document.asset_refs}
    for ref in plan.assets if plan is not None else []:
        resolved.setdefault(ref.asset_id, ref)
    styled = apply_edit_operations(narrated_document, operations, resolved_assets=resolved)
    if not curve:
        return _recorded(styled, roles_by_item, kept)
    # New shots of a movie duck under the voice like the clip they replaced.
    restyled = styled.model_dump(mode="python")
    restyled["clips"] = [
        (
            clip.model_copy(update={"volume_keyframes": _clip_keyframes(curve, clip)})
            if _sounding(clip, assets)
            else clip
        ).model_dump(mode="python")
        for clip in styled.clips
    ]
    return _recorded(EditDocumentV2.model_validate(restyled), roles_by_item, kept)


def _phrase_windows(
    words: Sequence[WordTiming], start: int, window: Window, fps: float
) -> list[Window]:
    """A voiced beat's phrase windows: each from its first word to the next phrase's first
    word, the first from the beat's start and the last to its end (spec 2026-11-13, 5.1)."""
    ranges = split_phrases(words)
    if not ranges:
        return [window]
    cuts = [window[0]]
    for first, _ in ranges[1:]:
        frame = min(window[1] - 1, start + round(words[first].start_seconds * fps))
        if frame > cuts[-1]:
            cuts.append(frame)
    bounds = [*cuts, window[1]]
    return list(pairwise(bounds))


def _assignments(
    plan: DraftPlan,
    document: EditDocumentV2,
    voices: Mapping[str, VoicedBeat],
    windows: Mapping[str, list[Window]],
    fps: float,
) -> dict[BeatId, BeatAssignment]:
    """The plan in frames, beat by beat, sharing one record of used shots. A beat whose phrases
    no longer match the plan's (an edited script) keeps the phrase-start rhythm only."""
    main_tracks = {track.track_id for track in document.tracks if track.kind == "main_video"}
    mains = sorted(
        (
            c
            for c in document.clips
            if isinstance(c, TimelineVideoClip) and c.track_id in main_tracks
        ),
        key=lambda c: c.from_frame,
    )
    refs = {ref.asset_id: ref for ref in (*document.asset_refs, *plan.assets)}
    frames = {
        asset_id: ref.duration_in_frames
        for asset_id, ref in refs.items()
        if ref.kind == "video" and ref.duration_in_frames
    }
    used: set[str] = set()
    out: dict[BeatId, BeatAssignment] = {}
    for beat_plan in sorted(plan.beats, key=lambda b: BEAT_ORDER.index(b.beat)):
        beat = beat_plan.beat
        voice = voices.get(beat)
        phrase_windows = windows.get(beat)
        if voice is None or phrase_windows is None:
            continue
        ranges = [(p.first_word, p.last_word) for p in beat_plan.phrases]
        if ranges != split_phrases(voice.words) or len(ranges) != len(phrase_windows):
            continue
        at = phrase_windows[0][0]
        under = next((c for c in mains if c.from_frame <= at < c.end_frame), None)
        out[beat] = assign_beat(
            beat,
            beat_plan.phrases,
            phrase_windows,
            plan,
            fps,
            under.asset_id if under is not None else None,
            under.source_from_frame + (at - under.from_frame) if under is not None else 0,
            beat in BACKGROUND_BEATS,
            used,
            frames,
        )
    return out


def _recorded(
    document: EditDocumentV2, roles_by_item: dict[str, str] | None, kept: list[str]
) -> EditDocumentV2:
    """The style record after a write: each beat's shots as left, and the beats kept."""
    if document.style is None:
        return document
    style = document.style.model_copy(
        update={
            "voiced": True,
            "cuts": beat_fingerprints(document, roles_by_item),
            "kept": [beat for beat in BEAT_ORDER if beat in kept],
        }
    )
    return document.model_copy(update={"style": style})


def sentence_ends(words: Sequence[WordTiming], start: int, fps: float) -> list[int]:
    """The frames a voice's sentences end on: a word ending in `.`, `?`, `!` or an ellipsis."""
    return [
        start + round(word.end_seconds * fps)
        for word in words
        if word.text.rstrip().endswith((".", "?", "!", "\u2026"))
    ]


def _tokens(text: str) -> list[str]:
    return [token for token in re.split(r"[^\w-]+", text.casefold()) if token]


def spoken_at(line: str, words: Sequence[WordTiming], start: int, fps: float) -> int | None:
    """The frame the voice first says a word of the sentence a card line repeats: the sentence
    holding most of the line's words (at least half; on a tie the shorter, closer one), or None
    when no sentence does (stage1, 2026-11-12)."""
    wanted = set(_tokens(line))
    best: tuple[int, float, int] | None = None  # (shared words, closeness, frame)
    sentence: list[WordTiming] = []
    for word in words:
        sentence.append(word)
        if word.text.rstrip().endswith((".", "?", "!", "…")) or word is words[-1]:
            said = [w for w in sentence if wanted & set(_tokens(w.text))]
            shared = len(wanted & {t for w in said for t in _tokens(w.text)})
            score = (shared, shared / len(sentence))
            if 2 * shared >= len(wanted) > 0 and (best is None or score > best[:2]):
                best = (*score, start + round(said[0].start_seconds * fps))
            sentence = []
    return None if best is None else best[2]


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


def _pack(clips: Sequence, window: Window) -> dict[str, Window]:
    """Lay clips end to end over a window in their order, each a share as long as it was."""
    ordered = sorted(clips, key=lambda clip: (clip.from_frame, clip.clip_id))
    total = sum(clip.duration_in_frames for clip in ordered)
    span = window[1] - window[0]
    result: dict[str, Window] = {}
    done = 0
    for clip in ordered:
        start = window[0] + span * done // total
        done += clip.duration_in_frames
        result[clip.clip_id] = (start, max(window[0] + span * done // total, start + 1))
    return result


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
            else frames_left(clip, asset)
        )
        update["hold_after_source"] = remaining is not None and length > remaining
        update["volume_keyframes"] = []
        # A push-in across the clip stays across the clip in its new window (spec 2026-11-09).
        update["moves"] = stretch_moves(clip.moves, clip.duration_in_frames, length)
        # Video fades (Tier 2) stay inside a clip the new window shortened, as fit_fades keeps them.
        fade_in = min(clip.fade_in_frames, length)
        update.update(
            fade_in_frames=fade_in, fade_out_frames=min(clip.fade_out_frames, length - fade_in)
        )
        # Blur turns on with the first narration only; the operator may switch it off after.
        if first and clip.blur_regions and any(s < end and start < e for s, e in voiced):
            update["blur_enabled"] = True
    if isinstance(clip, TimelineAudioClip):
        asset = assets.get(clip.asset_id)
        if asset is not None and asset.duration_in_frames is not None:
            # Audio cannot hold a frame: a stretched clip stops where its asset ends.
            length = max(1, min(length, frames_left(clip, asset)))
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


def _pages(
    words: Sequence[WordTiming], fps: float, length: int, page_words: int = PAGE_WORDS
) -> list[CaptionCue]:
    """Pages of at most `page_words` words or 1.2 s, each word timed relative to its page."""
    pages: list[list[WordTiming]] = []
    for word in words:
        if not word.text.strip():
            continue
        if (
            pages
            and len(pages[-1]) < page_words
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


def _with_headline(
    document: EditDocumentV2, roles_by_item: dict[str, str] | None, headline: str
) -> EditDocumentV2:
    """The main title, the first heading of the main beat, reads `headline`; a title a person
    edited stays theirs."""
    beats = clip_beats(document, roles_by_item)
    title = next(
        (
            clip
            for clip in sorted(document.clips, key=lambda clip: clip.from_frame)
            if isinstance(clip, TimelineTextClip)
            and beats.get(clip.clip_id) == "main"
            and clip.style_slot not in ("credit", "card")
        ),
        None,
    )
    if title is None or title.ownership == "user_edited" or title.heading == headline:
        return document
    return document.model_copy(
        update={
            "clips": [
                clip.model_copy(update={"heading": headline}) if clip is title else clip
                for clip in document.clips
            ]
        }
    )


def _sounding(clip: object, assets: Mapping[str, AssetRef]) -> bool:
    """A video clip whose media carries sound: it ducks under the narration."""
    if not isinstance(clip, TimelineVideoClip):
        return False
    asset = assets.get(clip.asset_id)
    return asset is not None and asset.kind == "video" and asset.has_audio


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
