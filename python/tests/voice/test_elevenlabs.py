"""The ElevenLabs adapter, offline through httpx.MockTransport."""

import base64
import json

import httpx
import pytest

from thoth_control_plane.voice.adapters.elevenlabs import ElevenLabsVoice, words_from_alignment
from thoth_control_plane.voice.ports import VoiceRejected, VoiceRequest, VoiceUnavailable

ALIGNMENT = {
    "characters": list("Halo,  dunia!"),
    "character_start_times_seconds": [
        0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.55, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1,
    ],
    "character_end_times_seconds": [
        0.1, 0.2, 0.3, 0.4, 0.5, 0.55, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2,
    ],
}


def test_alignment_groups_runs_of_non_space_characters_into_words() -> None:
    words = words_from_alignment(ALIGNMENT)
    assert [(w.text, w.start_seconds, w.end_seconds) for w in words] == [
        ("Halo,", 0.0, 0.5),
        ("dunia!", 0.6, 1.2),
    ]


async def test_synthesize_posts_with_timestamps_and_decodes_audio() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers["xi-api-key"]
        seen["body"] = json.loads(request.content)
        audio = base64.b64encode(b"MP3").decode()
        return httpx.Response(200, json={"audio_base64": audio, "alignment": ALIGNMENT})

    voice = await ElevenLabsVoice("secret-key", transport=httpx.MockTransport(handler)).synthesize(
        VoiceRequest(text="Halo, dunia!", voice_id="plgKUYgnlZ1DCNh54DwJ")
    )
    assert voice.audio == b"MP3"
    assert voice.media_type == "audio/mpeg"
    assert voice.duration_seconds == 1.2
    assert "/v1/text-to-speech/plgKUYgnlZ1DCNh54DwJ/with-timestamps" in seen["url"]
    assert "output_format=mp3_44100_128" in seen["url"]
    assert seen["key"] == "secret-key"
    assert seen["body"]["model_id"] == "eleven_multilingual_v2"
    assert seen["body"]["voice_settings"] == {"speed": 1.0}
    assert "language_code" not in seen["body"]


@pytest.mark.parametrize(
    ("status", "error"),
    [(401, VoiceRejected), (422, VoiceRejected), (429, VoiceUnavailable), (503, VoiceUnavailable)],
)
async def test_errors_map_and_never_carry_the_key(status, error) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status, json={"detail": {"status": "x"}})
    )
    with pytest.raises(error) as caught:
        await ElevenLabsVoice("secret-key", transport=transport).synthesize(
            VoiceRequest(text="a", voice_id="v")
        )
    assert "secret-key" not in str(caught.value)
    assert "secret-key" not in repr(caught.value)
    assert str(caught.value) == f"elevenlabs_http_{status}"


async def test_a_connection_failure_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(VoiceUnavailable):
        await ElevenLabsVoice("k", transport=httpx.MockTransport(handler)).synthesize(
            VoiceRequest(text="a", voice_id="v")
        )
