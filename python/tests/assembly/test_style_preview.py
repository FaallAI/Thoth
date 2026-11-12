"""The cut preview: a style's cuts from the script's estimated timing, before any voice."""

from __future__ import annotations

from tests.assembly.test_narration_timeline import PRESET, ROLES, draft
from thoth_control_plane.assembly.style_preview import estimated_words, preview_document
from thoth_control_plane.domain.edit_document_v2 import (
    TimelineAudioClip,
    TimelineCaptionClip,
    TimelineVideoClip,
)
from thoth_control_plane.domain.narration import NarrationPreset, NarrationScript
from thoth_control_plane.domain.style_templates import BUILT_IN_STYLES

SCRIPT = NarrationScript.model_validate(
    {
        "beats": [
            {"beat": "hook", "text": "Satu dua tiga. Empat lima?", "card_line": "Kok bisa ya?"},
            {"beat": "main", "text": "Enam tujuh delapan sembilan sepuluh. Sebelas dua belas."},
            {"beat": "reactions", "text": "Warganet malah tertawa."},
        ],
        "sfx_cues": [],
    }
)


def test_estimated_words_follow_the_preset_rate() -> None:
    script = NarrationScript.model_validate(
        {"beats": [{"beat": "hook", "text": "a b c d e f g h i."}], "sfx_cues": []}
    )
    words = estimated_words(script, NarrationPreset(words_per_second=3.0))
    assert len(words["hook"]) == 9
    assert words["hook"][-1].end_seconds == 3.0


def test_the_preview_is_cut_like_the_style() -> None:
    b = BUILT_IN_STYLES["style_b"]
    preview = preview_document(draft(), b, SCRIPT, PRESET, ROLES)
    shots = [
        c
        for c in preview.clips
        if isinstance(c, TimelineVideoClip) and c.clip_id.startswith("clip_style_")
    ]
    assert shots and all(c.duration_in_frames <= 90 + 30 for c in shots)
    assert {c.style_slot for c in preview.clips if isinstance(c, TimelineCaptionClip)} == {
        "kinetic"
    }
    # No voice is made for a preview: its stand-in voices never reach the document.
    assert not [
        c for c in preview.clips if isinstance(c, TimelineAudioClip) and "preview" in c.asset_id
    ]
    assert not [a for a in preview.asset_refs if "preview" in a.asset_id]


def test_the_preview_shows_the_card_lines() -> None:
    from thoth_control_plane.domain.edit_document_v2 import TimelineTextClip

    preview = preview_document(draft(), BUILT_IN_STYLES["style_b"], SCRIPT, PRESET, ROLES)
    cards = [c for c in preview.clips if isinstance(c, TimelineTextClip) and c.style_slot == "card"]
    assert [c.heading for c in cards] == ["Kok bisa ya?"]


def test_the_preview_skips_the_title_card_like_the_first_voice() -> None:
    # Deferred minor (2026-11-10): the first narration starts the main video after its title
    # card, so the preview does too.
    a = BUILT_IN_STYLES["style_a"]

    def main_starts(document) -> int:  # type: ignore[no-untyped-def]
        mains = {t.track_id for t in document.tracks if t.kind == "main_video"}
        return min(
            c.source_from_frame
            for c in document.clips
            if isinstance(c, TimelineVideoClip) and c.track_id in mains
        )

    assert main_starts(preview_document(draft(), a, SCRIPT, PRESET, ROLES)) < 30
    assert main_starts(preview_document(draft(), a, SCRIPT, PRESET, ROLES, intro_frames=30)) >= 30
