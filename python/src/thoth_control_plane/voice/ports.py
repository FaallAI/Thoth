"""The voice port (spec 2026-10-18, section 9). Two providers; edge-tts is excluded (operator)."""

from __future__ import annotations

from typing import Annotated, Literal, Protocol

from pydantic import Field

from thoth_control_plane.domain.models import StrictModel


class VoiceRequest(StrictModel):
    text: Annotated[str, Field(min_length=1, max_length=5000)]
    language: Annotated[str, Field(min_length=2, max_length=8)] = "id"
    voice_id: Annotated[str, Field(min_length=1, max_length=200)]
    model: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    speed: Annotated[float, Field(ge=0.7, le=1.5)] = 1.0


class WordTiming(StrictModel):
    text: str
    start_seconds: float
    end_seconds: float


class SynthesizedVoice(StrictModel):
    audio: bytes
    media_type: Literal["audio/mpeg", "audio/wav"]
    duration_seconds: float
    word_timings: list[WordTiming] | None


class VoiceSynthesizer(Protocol):
    async def synthesize(self, request: VoiceRequest) -> SynthesizedVoice: ...


class VoiceUnavailable(RuntimeError):
    """Timeout, connection failure, HTTP 429 or 5xx: retryable."""


class VoiceRejected(ValueError):
    """Any other 4xx: not retryable. Carries the provider's code, never a credential."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class VoiceNotConfigured(RuntimeError):
    """The provider has no credentials or base URL."""
