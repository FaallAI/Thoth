"""ElevenLabs text-to-speech with character timestamps: the primary provider."""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote

import httpx

from thoth_control_plane import metering
from thoth_control_plane.voice.audio import probe_duration
from thoth_control_plane.voice.ports import (
    SynthesizedVoice,
    VoiceRejected,
    VoiceRequest,
    VoiceUnavailable,
    WordTiming,
)

#: The Rust engine's setting; `language_code` is ignored by the v2 multilingual models.
DEFAULT_MODEL = "eleven_multilingual_v2"
BASE_URL = "https://api.elevenlabs.io"


def words_from_alignment(alignment: dict[str, Any]) -> list[WordTiming]:
    """A word is a maximal run of non-whitespace characters, timed by its first and last."""
    words: list[WordTiming] = []
    text, start, end = "", 0.0, 0.0
    for char, char_start, char_end in zip(
        alignment["characters"],
        alignment["character_start_times_seconds"],
        alignment["character_end_times_seconds"],
        strict=True,
    ):
        if char.isspace():
            if text:
                words.append(WordTiming(text=text, start_seconds=start, end_seconds=end))
                text = ""
            continue
        if not text:
            start = char_start
        text, end = text + char, char_end
    if text:
        words.append(WordTiming(text=text, start_seconds=start, end_seconds=end))
    return words


def raise_for_status(response: httpx.Response, provider: str) -> None:
    if response.status_code < 400:
        return
    code = f"{provider}_http_{response.status_code}"
    if response.status_code == 429 or response.status_code >= 500:
        raise VoiceUnavailable(code)
    raise VoiceRejected(code)


class ElevenLabsVoice:
    def __init__(self, api_key: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._key = api_key
        self._transport = transport

    def __repr__(self) -> str:
        return "ElevenLabsVoice()"

    async def synthesize(self, request: VoiceRequest) -> SynthesizedVoice:
        body = {
            "text": request.text,
            "model_id": request.model or DEFAULT_MODEL,
            "voice_settings": {"speed": request.speed},
        }
        try:
            async with httpx.AsyncClient(
                base_url=BASE_URL, transport=self._transport, timeout=120
            ) as http:
                response = await http.post(
                    f"/v1/text-to-speech/{quote(request.voice_id, safe='')}/with-timestamps",
                    params={"output_format": "mp3_44100_128"},
                    headers={"xi-api-key": self._key},
                    json=body,
                )
        except httpx.HTTPError:
            raise VoiceUnavailable("elevenlabs_unreachable") from None
        raise_for_status(response, "elevenlabs")
        # Billed once accepted, before the body is decoded (spec 2026-10-20, 2.1).
        await metering.record_call(f"elevenlabs/{body['model_id']}", characters=len(request.text))
        try:
            payload = response.json()
            audio = base64.b64decode(payload["audio_base64"])
            alignment = payload.get("alignment")
            words = words_from_alignment(alignment) if alignment else None
        except (ValueError, KeyError, TypeError):
            # A proxy error page or a changed body shape: retryable, and never echoed back.
            raise VoiceUnavailable("elevenlabs_bad_response") from None
        duration = words[-1].end_seconds if words else probe_duration(audio)
        return SynthesizedVoice(
            audio=audio, media_type="audio/mpeg", duration_seconds=duration, word_timings=words
        )
