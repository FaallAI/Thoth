"""The OpenAI-compatible adapter (VoiceStudio and similar servers), offline."""

import io
import json
import wave

import httpx
import pytest

from thoth_control_plane.voice.adapters.openai_compatible import OpenAICompatibleVoice
from thoth_control_plane.voice.ports import VoiceRejected, VoiceRequest, VoiceUnavailable


def wav(seconds: float) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\0\0" * int(8000 * seconds))
    return buffer.getvalue()


async def test_speech_request_carries_model_voice_speed_and_language() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=wav(1.5), headers={"content-type": "audio/wav"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    voice = await OpenAICompatibleVoice(
        "http://voices.test/v1", None, http_client=client
    ).synthesize(VoiceRequest(text="Halo", voice_id="M1", model="supertonic3", speed=1.1))
    assert seen["path"] == "/v1/audio/speech"
    assert seen["body"] == {
        "model": "supertonic3",
        "voice": "M1",
        "input": "Halo",
        "response_format": "wav",
        "speed": 1.1,
        "language": "id",
    }
    assert voice.media_type == "audio/wav"
    assert voice.word_timings is None
    assert abs(voice.duration_seconds - 1.5) < 0.01


async def test_a_model_is_required_and_errors_map() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "x"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAICompatibleVoice("http://voices.test/v1", None, http_client=client)
    with pytest.raises(VoiceRejected):
        await adapter.synthesize(VoiceRequest(text="a", voice_id="v"))
    with pytest.raises(VoiceUnavailable):
        await adapter.synthesize(VoiceRequest(text="a", voice_id="v", model="m"))


async def test_a_client_error_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "licence not accepted"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(VoiceRejected) as caught:
        await OpenAICompatibleVoice("http://voices.test/v1", "k", http_client=client).synthesize(
            VoiceRequest(text="a", voice_id="v", model="m")
        )
    assert caught.value.code == "openai_compatible_http_403"
