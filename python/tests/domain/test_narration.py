"""The narration preset, script and the voice estimate (spec 2026-10-31 auto-draft)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from thoth_control_plane.domain.narration import (
    BEAT_ORDER,
    NarrationPreset,
    NarrationScript,
    ScriptBeat,
    VoiceEstimate,
    estimate_voice,
)


def test_the_preset_defaults_are_the_rust_values() -> None:
    preset = NarrationPreset()
    assert preset.language == "id"
    assert (preset.target_seconds, preset.words_per_second) == (45, 3.0)
    assert (preset.voice_id, preset.voice_model) == (
        "plgKUYgnlZ1DCNh54DwJ",
        "eleven_v4",
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
        {("provider_call", "elevenlabs/eleven_v4", "character"): 0.0003},
    )
    assert priced.usd == pytest.approx(0.0018)

    wildcard = estimate_voice(
        script, NarrationPreset(), {("provider_call", "*", "character"): 0.001}
    )
    assert wildcard.usd == pytest.approx(0.006)


def test_estimate_voice_counts_tags_on_v4_and_strips_on_v2() -> None:
    """Eleven v4 bills the tags it reads; an older model is sent the spoken words only."""
    script = NarrationScript(
        beats=[ScriptBeat(beat="hook", text="[curious] Halo dunia!")], sfx_cues=[]
    )
    assert estimate_voice(script, NarrationPreset(voice_model="eleven_v4"), {}).characters == 21
    v2 = NarrationPreset(voice_model="eleven_multilingual_v2")
    assert estimate_voice(script, v2, {}).characters == 11


def test_the_estimate_names_the_model_it_counted_for() -> None:
    """The dashboard prices a re-voiced beat the way this estimate counted (tags or not)."""
    script = NarrationScript(beats=[ScriptBeat(beat="hook", text="Halo")], sfx_cues=[])
    v2 = NarrationPreset(voice_model="eleven_multilingual_v2")
    assert estimate_voice(script, v2, {}).voice_model == "eleven_multilingual_v2"
    assert VoiceEstimate(characters=1, provider="elevenlabs", voice_id="v").voice_model is None
