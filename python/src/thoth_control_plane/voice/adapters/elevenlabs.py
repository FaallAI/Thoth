"""ElevenLabs text-to-speech with character timestamps: the primary provider."""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote

import httpx

from thoth_control_plane import metering
from thoth_control_plane.voice.audio import probe_duration
from thoth_control_plane.voice.audio_tags import (
    AUDIO_TAG_RE,
    strip_audio_tags,
    supports_audio_tags,
)
from thoth_control_plane.voice.ports import (
    SynthesizedVoice,
    VoiceRejected,
    VoiceRequest,
    VoiceUnavailable,
    WordTiming,
)

#: Reads inline audio tags (spec 2026-11-24); it takes no `speed`, and v2 ignores `language_code`.
DEFAULT_MODEL = "eleven_v4"
BASE_URL = "https://api.elevenlabs.io"
_CLOSING_PUNCTUATION = frozenset(".,!?;:")
#: Models with no speed setting (ElevenLabs docs): v3 reads no tags here, but takes no speed.
_NO_SPEED = ("eleven_v3", "eleven_v4")


def _tag_end(characters: list[str], index: int) -> int | None:
    """The index of the `]` closing an audio tag that opens at `index`, if one does."""
    for close in range(index + 1, min(len(characters), index + 42)):
        if characters[close] == "[":
            return None
        if characters[close] == "]":
            span = "".join(characters[index : close + 1])
            return close if AUDIO_TAG_RE.fullmatch(span) else None
    return None


def words_from_alignment(alignment: dict[str, Any]) -> list[WordTiming]:
    """A word is a maximal run of non-whitespace characters, timed by its first and last.

    Eleven v4 times its audio tags like words; a tag is skipped and ends the word before it,
    so captions, phrases and SFX positions only ever see spoken words.
    """
    characters = list(alignment["characters"])
    starts = alignment["character_start_times_seconds"]
    ends = alignment["character_end_times_seconds"]
    if not len(characters) == len(starts) == len(ends):
        raise ValueError("alignment arrays differ in length")
    words: list[WordTiming] = []
    text, start, end = "", 0.0, 0.0
    after_tag = False  # punctuation right after a tag closes the word before it
    index = 0
    while index < len(characters):
        char, char_start, char_end = characters[index], starts[index], ends[index]
        close = _tag_end(characters, index) if char == "[" else None
        if char.isspace() or close is not None:
            if text:
                words.append(WordTiming(text=text, start_seconds=start, end_seconds=end))
                text = ""
            after_tag = close is not None or (after_tag and not char.isspace())
            index = close + 1 if close is not None else index + 1
            continue
        if after_tag and not text and words and char in _CLOSING_PUNCTUATION:
            # "Halo [curious]." is spoken "Halo.", as strip_audio_tags writes it.
            last = words[-1]
            words[-1] = last.model_copy(update={"text": last.text + char, "end_seconds": char_end})
            index += 1
            continue
        after_tag = False
        if not text:
            start = char_start
        text, end = text + char, char_end
        index += 1
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
        model_id = request.model or DEFAULT_MODEL
        body: dict[str, Any] = {"model_id": model_id}
        settings: dict[str, Any] = {}
        spoken = strip_audio_tags(request.text)
        if not spoken:
            # Tags alone are no speech: never paid for, on any model.
            raise VoiceRejected("empty_text_after_tag_strip")
        if supports_audio_tags(model_id):
            # v4 speaks the tags as delivery and takes the language.
            body["text"] = request.text
            body["language_code"] = request.language
        else:
            # An older model would read a tag aloud, so it never sees one.
            body["text"] = spoken
        if not model_id.startswith(_NO_SPEED):
            settings["speed"] = request.speed
        if request.stability is not None:
            settings["stability"] = request.stability
        if settings:
            body["voice_settings"] = settings
        # A neighbour's mood must not colour this beat; its words still stitch the intonation.
        neighbours = {"previous_text": request.previous_text, "next_text": request.next_text}
        for field, neighbour in neighbours.items():
            if neighbour and (plain := strip_audio_tags(neighbour)):
                body[field] = plain
        if request.previous_request_ids:
            body["previous_request_ids"] = request.previous_request_ids[-3:]
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
        # The provider's own `character-cost` header is what it bills; the text length is the
        # fallback when the header is missing.
        cost = response.headers.get("character-cost", "")
        await metering.record_call(
            f"elevenlabs/{body['model_id']}",
            characters=int(cost) if cost.isdigit() else len(body["text"]),
        )
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
            audio=audio,
            media_type="audio/mpeg",
            duration_seconds=duration,
            word_timings=words,
            request_id=response.headers.get("request-id") or None,
        )
