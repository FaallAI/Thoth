"""Does a video carry burned-in speech captions? One structured vision call over OpenRouter.

Asked only when the rules still see captions (spec amendment, 2026-10-12): signage, banners,
screens, and title cards read as captions would otherwise mute an original's audio.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import httpx
from pydantic import BaseModel, Field

from thoth_control_plane import metering
from thoth_control_plane.attribution.ports import Frame

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
TIMEOUT_SECONDS = 60.0
MAX_FRAMES = 3
PROMPT = (
    "These are frames from a short video. Does the video carry burned-in speech captions: "
    "subtitles added in editing that transcribe what someone is saying? Text that is part of "
    "the filmed scene (signs, banners, screens, clothing, logos), a title card or headline, a "
    "watermark, or an app's interface does not count. Answer in JSON."
)


class CaptionCheck(BaseModel):
    speech_captions: bool = Field(description="true only for burned-in speech subtitles")


class AgnoCaptionJudge:
    def __init__(self, api_key: str, model: str, *, base_url: str = OPENROUTER_BASE_URL) -> None:
        self._key = api_key
        self._model = model
        self._base_url = base_url

    async def speech_captions(self, frames: Sequence[Frame]) -> bool | None:
        from agno.agent import Agent
        from agno.media import Image
        from agno.models.openai.like import OpenAILike

        # agno builds an AsyncOpenAI per request; left to the SDK, its httpx client is
        # closed by garbage collection, on whichever loop runs then (a workflow thread).
        http = httpx.AsyncClient(timeout=TIMEOUT_SECONDS)
        agent = Agent(
            model=OpenAILike(
                id=self._model,
                api_key=self._key,
                base_url=self._base_url,
                timeout=TIMEOUT_SECONDS,
                max_retries=1,
                http_client=http,
            ),
            output_schema=CaptionCheck,
            use_json_mode=True,
            telemetry=False,
        )
        images = [Image(content=f.jpeg, mime_type="image/jpeg") for f in frames[:MAX_FRAMES]]
        try:
            run = await agent.arun(input=PROMPT, images=images)
        except Exception:
            logger.warning("caption check unavailable; the rule-based verdict stands")
            return None
        finally:
            await http.aclose()
        await metering.record_model_run(self._model, run)
        return run.content.speech_captions if isinstance(run.content, CaptionCheck) else None
