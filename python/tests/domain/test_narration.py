"""The narration preset, script and the voice estimate (spec 2026-10-31 auto-draft)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from thoth_control_plane.domain.narration import (
    BEAT_ORDER,
    NarrationPreset,
    NarrationScript,
    ScriptBeat,
    estimate_voice,
)


def test_the_preset_defaults_are_the_rust_values() -> None:
    preset = NarrationPreset()
    assert preset.language == "id"
    assert (preset.target_seconds, preset.words_per_second) == (45, 3.0)
    assert (preset.voice_id, preset.voice_model) == (
        "plgKUYgnlZ1DCNh54DwJ",
        "eleven_multilingual_v2",
    )
    assert (preset.duck_volume, preset.leak_volume, preset.lead_in_seconds) == (0.12, 0.45, 1.6)
    assert preset.max_sfx_cues == 3


def test_the_beats_follow_the_story_order() -> None:
    assert BEAT_ORDER == ("hook", "main", "evidence", "reactions", "footage", "outro")


@pytest.mark.parametrize(
    "beats",
    [
        [("main", "a"), ("main", "b")],
        [("main", "a"), ("hook", "b")],
    ],
)
def test_a_script_refuses_a_repeated_or_unordered_beat(beats: list[tuple[str, str]]) -> None:
    with pytest.raises(ValidationError):
        NarrationScript(
            beats=[ScriptBeat(beat=beat, text=text) for beat, text in beats],  # type: ignore[arg-type]
            sfx_cues=[],
        )


def test_the_estimate_counts_characters_and_prices_them_when_a_price_exists() -> None:
    script = NarrationScript(
        beats=[ScriptBeat(beat="hook", text="abcd"), ScriptBeat(beat="main", text="ef")],
        sfx_cues=[],
    )
    unpriced = estimate_voice(script, NarrationPreset(), {})
    assert (unpriced.characters, unpriced.usd) == (6, None)
    assert (unpriced.provider, unpriced.voice_id) == ("elevenlabs", "plgKUYgnlZ1DCNh54DwJ")

    priced = estimate_voice(
        script,
        NarrationPreset(),
        {("provider_call", "elevenlabs/eleven_multilingual_v2", "character"): 0.0003},
    )
    assert priced.usd == pytest.approx(0.0018)

    wildcard = estimate_voice(
        script, NarrationPreset(), {("provider_call", "*", "character"): 0.001}
    )
    assert wildcard.usd == pytest.approx(0.006)
