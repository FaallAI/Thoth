"""Structured vision answers through Agno over OpenRouter's OpenAI-compatible endpoint.

Agno sends anonymous telemetry by default; it is switched off here. The model is asked for
prose (a headline, a scene, an icon description) or one class, never for a platform name or an
account: those decisions belong to Jev and the code.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TypeVar

from pydantic import BaseModel

from thoth_control_plane.attribution.ports import CoverReading, Frame, VisualClass, VisualKind

logger = logging.getLogger(__name__)

# OpenRouter only (operator, 2026-10-09): one key for vision and Jev decisions.
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
TIMEOUT_SECONDS = 60.0
MAX_FRAMES = 3
COVER_PROMPT = (
    "These are the cover and the first frames of a short video. Copy the text printed on the "
    "image, describe the scene in one sentence, and describe any app or platform logo you see "
    "and where it is. Answer in JSON."
)
CLASSIFY_PROMPT = (
    "These are frames of a short video. Is it raw footage of an event, or commentary (a person "
    "talking to the camera about it, a news anchor, a slideshow, or a reaction)? Answer in JSON."
)
Schema = TypeVar("Schema", bound=BaseModel)


class AgnoVisionReader:
    def __init__(self, api_key: str, model: str, *, base_url: str = OPENROUTER_BASE_URL) -> None:
        self._key = api_key
        self._model = model
        self._base_url = base_url

    async def read_cover(self, frames: Sequence[Frame]) -> CoverReading | None:
        return await self._run(CoverReading, COVER_PROMPT, frames)

    async def classify(self, frames: Sequence[Frame]) -> VisualKind | None:
        result = await self._run(VisualClass, CLASSIFY_PROMPT, frames)
        return result.kind if result is not None else None

    async def _run(
        self, schema: type[Schema], prompt: str, frames: Sequence[Frame]
    ) -> Schema | None:
        from agno.agent import Agent
        from agno.media import Image
        from agno.models.openai.like import OpenAILike

        agent = Agent(
            model=OpenAILike(
                id=self._model,
                api_key=self._key,
                base_url=self._base_url,
                timeout=TIMEOUT_SECONDS,
                max_retries=1,
            ),
            output_schema=schema,
            use_json_mode=True,
            telemetry=False,
        )
        images = [
            Image(content=frame.jpeg, mime_type="image/jpeg") for frame in frames[:MAX_FRAMES]
        ]
        try:
            run = await agent.arun(input=prompt, images=images)
        except Exception:
            logger.warning("vision read unavailable; attribution continues without it")
            return None
        return run.content if isinstance(run.content, schema) else None
