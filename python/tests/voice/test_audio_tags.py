"""Inline ElevenLabs audio tags (spec 2026-11-24, section 5.1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from thoth_control_plane.voice.audio_tags import (
    AUDIO_TAG_RE,
    sanitize_script_tags,
    strip_audio_tags,
    supports_audio_tags,
)
from thoth_control_plane.voice.ports import VoiceRequest


def test_supports_audio_tags_matches_only_eleven_v4_family() -> None:
    assert supports_audio_tags("eleven_v4")
    assert supports_audio_tags("eleven_v4_turbo")
    assert not supports_audio_tags("eleven_multilingual_v2")
    assert not supports_audio_tags("eleven_v3")
    assert not supports_audio_tags("")
    assert not supports_audio_tags(None)


def test_strip_audio_tags_removes_single_multiword_and_adjacent_tags() -> None:
    assert strip_audio_tags("[curious] Halo, [amused] dunia!") == "Halo, dunia!"
    assert strip_audio_tags("[clears throat] Mulai sekarang.") == "Mulai sekarang."
    assert strip_audio_tags("[curious]Halo [sighs]") == "Halo"
    assert strip_audio_tags("suka, [amused] tapi") == "suka, tapi"
    assert strip_audio_tags("dunia [excited]!") == "dunia!"
    assert strip_audio_tags("Tahun [2026] tetap ada.") == "Tahun [2026] tetap ada."
    assert strip_audio_tags("[curious tanpa tutup") == "[curious tanpa tutup"
    assert AUDIO_TAG_RE.fullmatch("[clears throat]")
    assert not AUDIO_TAG_RE.fullmatch("[2026]")


def test_sanitize_script_tags_keeps_allowed_normalizes_and_caps() -> None:
    allowed = frozenset({"curious", "amused", "excited"})
    assert (
        sanitize_script_tags("[CURIOUS] Halo [tertawa] [amused] dunia [excited]!", allowed, max_tags=2)
        == "[curious] Halo [amused] dunia!"
    )
    assert (
        sanitize_script_tags("[curious] Halo [jeda 2 detik] dunia.", frozenset({"curious"}))
        == "[curious] Halo dunia."
    )
    assert sanitize_script_tags("[curious] Halo.", frozenset()) == "Halo."


def test_voice_request_stability_defaults_none_and_bounds() -> None:
    assert VoiceRequest(text="Halo", voice_id="v").stability is None
    assert VoiceRequest(text="Halo", voice_id="v", stability=0.45).stability == 0.45
    with pytest.raises(ValidationError):
        VoiceRequest(text="Halo", voice_id="v", stability=1.5)
