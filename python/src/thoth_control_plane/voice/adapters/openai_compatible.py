"""Any OpenAI-compatible speech server: VoiceStudio, OpenAI, or another self-hosted one.

VoiceStudio is used only as a separate, unmodified service over this endpoint (AGPL); `model`
selects its engine. No word timings: a caller that needs them aligns the audio itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx

from thoth_control_plane.voice.audio import probe_duration
from thoth_control_plane.voice.ports import (
    SynthesizedVoice,
    VoiceRejected,
    VoiceRequest,
    VoiceUnavailable,
)


class OpenAICompatibleVoice:
    def __init__(
        self, base_url: str, api_key: str | None, *, http_client: httpx.AsyncClient | None = None
    ) -> None:
        # openai ships with the acquisition extra; the base install's CLI must still load (CI).
        import openai

        self._client = openai.AsyncOpenAI(
            base_url=base_url, api_key=api_key or "unused", http_client=http_client, max_retries=0
        )

    def __repr__(self) -> str:
        return "OpenAICompatibleVoice()"

    async def synthesize(self, request: VoiceRequest) -> SynthesizedVoice:
        if not request.model:
            raise VoiceRejected("openai_compatible_model_required")
        import openai

        try:
            response = await self._client.audio.speech.create(
                model=request.model,
                voice=request.voice_id,
                input=request.text,
                response_format="wav",
                speed=request.speed,
                extra_body={"language": request.language},
            )
        except openai.APIStatusError as error:
            code = f"openai_compatible_http_{error.status_code}"
            if error.status_code == 429 or error.status_code >= 500:
                raise VoiceUnavailable(code) from None
            raise VoiceRejected(code) from None
        except openai.APIConnectionError:
            raise VoiceUnavailable("openai_compatible_unreachable") from None
        audio = response.content
        return SynthesizedVoice(
            audio=audio,
            media_type="audio/wav",
            duration_seconds=probe_duration(audio),
            word_timings=None,
        )
