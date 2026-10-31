"""Story beats on the server, the same answer Studio's ``story/story_beats.ts`` gives.

A clip's beat comes from its ``source_role``; a clip saved before Story mode is found through the
inventory item its id names (``clip_<item_id>``); any other clip takes the beat of its scene's
main clip. Only ``source_role`` ever names Hook or Outro. The shared cases in
``dashboard/src/features/studio/story_beat_cases.json`` hold both sides to one answer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from thoth_control_plane.domain.edit_document_v2 import EditDocumentV2
from thoth_control_plane.domain.narration import BEAT_ORDER, BeatId

ROLE_BEAT: dict[str, BeatId] = {
    "main": "main",
    "main_footage": "main",
    "slide": "main",
    "post_card": "evidence",
    "profile_card": "evidence",
    "profile_page": "evidence",
    "comment_card": "reactions",
    "comment": "reactions",
    "footage": "footage",
    "creator_footage": "footage",
    "creator_photo": "footage",
    "hook": "hook",
    "outro": "outro",
}


@dataclass(frozen=True)
class BeatSpan:
    beat: BeatId
    clip_ids: list[str]
    start_frame: int
    duration_in_frames: int


def clip_beats(
    document: EditDocumentV2, roles_by_item: Mapping[str, str] | None = None
) -> dict[str, BeatId]:
    """Every clip that has a beat, keyed by clip ID."""
    roles = roles_by_item or {}
    kind_of = {track.track_id: track.kind for track in document.tracks}
    result: dict[str, BeatId] = {}
    for clip in document.clips:
        role = clip.source_role or roles.get(clip.clip_id.removeprefix("clip_"))
        if role in ROLE_BEAT:
            result[clip.clip_id] = ROLE_BEAT[role]
    # A scene's other clips (its title, a quoted comment) follow the scene's main clip.
    scene_beat: dict[str, BeatId] = {}
    ranked = sorted(document.clips, key=lambda clip: kind_of.get(clip.track_id) != "main_video")
    for clip in ranked:
        beat = result.get(clip.clip_id)
        if clip.scene_id and beat and beat not in {"hook", "outro"}:
            scene_beat.setdefault(clip.scene_id, beat)
    for clip in document.clips:
        if clip.clip_id not in result and clip.scene_id in scene_beat:
            result[clip.clip_id] = scene_beat[clip.scene_id]
    return result


def beat_spans(
    document: EditDocumentV2, roles_by_item: Mapping[str, str] | None = None
) -> list[BeatSpan]:
    """The visible clips of each beat and the frames they cover, earliest beat first."""
    beats = clip_beats(document, roles_by_item)
    grouped: dict[BeatId, list] = {}
    for clip in document.clips:
        beat = beats.get(clip.clip_id)
        if beat is None or clip.hidden:
            continue
        grouped.setdefault(beat, []).append(clip)
    spans = []
    for beat, clips in grouped.items():
        ordered = sorted(clips, key=lambda clip: clip.from_frame)
        start = ordered[0].from_frame
        end = max(clip.end_frame for clip in ordered)
        spans.append(BeatSpan(beat, [clip.clip_id for clip in ordered], start, end - start))
    return sorted(spans, key=lambda span: (span.start_frame, BEAT_ORDER.index(span.beat)))
