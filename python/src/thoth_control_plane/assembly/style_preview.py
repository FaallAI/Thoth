"""The cut preview: a style's cuts from the script's estimated timing, before any voice is paid
for (spec 2026-11-10, 6).

The same narration writer runs over stand-in voices timed at the preset's words per second, so
the preview retimes the beats and cuts them exactly as the real voice will, then drops the
stand-ins. It is computed on request and never saved.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from thoth_control_plane.assembly.narration_timeline import VoicedBeat, narrate_document
from thoth_control_plane.domain.edit_document_v2 import AssetRef, EditDocumentV2, TimelineAudioClip
from thoth_control_plane.domain.narration import BeatId, NarrationPreset, NarrationScript
from thoth_control_plane.domain.style_templates import StyleTemplate
from thoth_control_plane.voice.ports import WordTiming

PREVIEW_PREFIX = "asset_preview_voice_"


def estimated_words(
    script: NarrationScript, preset: NarrationPreset
) -> dict[BeatId, list[WordTiming]]:
    """Each beat's words, one after another at the preset's words per second."""
    step = 1.0 / preset.words_per_second
    return {
        beat.beat: [
            WordTiming(text=word, start_seconds=index * step, end_seconds=(index + 1) * step)
            for index, word in enumerate(beat.text.split())
        ]
        for beat in script.beats
        if beat.text.split()
    }


def preview_document(
    document: EditDocumentV2,
    template: StyleTemplate,
    script: NarrationScript,
    preset: NarrationPreset,
    roles_by_item: Mapping[str, str] | None = None,
) -> EditDocumentV2:
    """The draft as the style will cut it once voiced, with no voice in it."""
    fps = document.canvas.fps
    voiced = []
    for beat, words in estimated_words(script, preset).items():
        seconds = words[-1].end_seconds
        voiced.append(
            VoicedBeat(
                beat=beat,
                asset=AssetRef(
                    asset_id=f"{PREVIEW_PREFIX}{beat}",
                    project_id=document.project_id,
                    kind="audio",
                    duration_in_frames=math.ceil(seconds * fps),
                    has_audio=True,
                    validation_state="ready",
                ),
                duration_seconds=seconds,
                words=words,
            )
        )
    cards = {beat.beat: beat.card_line for beat in script.beats if beat.card_line}
    narrated = narrate_document(
        document,
        voiced,
        [],
        preset,
        roles_by_item,
        place_sfx=False,
        style=template,
        card_lines=cards,
    )
    stand_ins = {
        clip.clip_id
        for clip in narrated.clips
        if isinstance(clip, TimelineAudioClip) and clip.asset_id.startswith(PREVIEW_PREFIX)
    }
    payload = narrated.model_dump(mode="python")
    payload["clips"] = [c for c in payload["clips"] if c["clip_id"] not in stand_ins]
    payload["tracks"] = [
        {**track, "clip_ids": [i for i in track["clip_ids"] if i not in stand_ins]}
        for track in payload["tracks"]
    ]
    payload["asset_refs"] = [
        a for a in payload["asset_refs"] if not a["asset_id"].startswith(PREVIEW_PREFIX)
    ]
    return EditDocumentV2.model_validate(payload)
