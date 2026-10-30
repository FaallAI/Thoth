"""Structured vision answers through Agno over OpenRouter's OpenAI-compatible endpoint.

Agno sends anonymous telemetry by default; it is switched off here. The model is asked for
prose (a headline, a scene, an icon description) or one class, never for a platform name or an
account: those decisions belong to Jev and the code.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TypeVar

import httpx
from pydantic import BaseModel

from thoth_control_plane import metering
from thoth_control_plane.attribution.ports import (
    AttributionError,
    CoverReading,
    Frame,
    VisualClass,
    VisualKind,
)

logger = logging.getLogger(__name__)

# OpenRouter only (operator, 2026-10-09): one key for vision and Jev decisions.
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
TIMEOUT_SECONDS = 60.0
MAX_FRAMES = 3
COVER_FRAMES = 6
COVER_PROMPT = (
    "These are the cover and frames from across a short video. Copy the text printed on the "
    "image, describe the scene in one sentence, describe any app or platform logo you see "
    "and where it is, and list every @username or account name printed on the image exactly "
    "as written. Also say whether this video reacts to another post: a screenshot of it, the "
    "other video inside this one, or a person talking about it. Say what that other post is "
    "(video, text, image) and, for each image in order, whether it shows the creator of this "
    "video, the other post, both, or neither. Answer in JSON."
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

    async def read_cover(self, frames: Sequence[Frame]) -> CoverReading:
        return await self._run(CoverReading, COVER_PROMPT, frames[:COVER_FRAMES])

    async def classify(self, frames: Sequence[Frame]) -> VisualKind:
        return (await self._run(VisualClass, CLASSIFY_PROMPT, frames[:MAX_FRAMES])).kind

    async def _run(self, schema: type[Schema], prompt: str, frames: Sequence[Frame]) -> Schema:
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
            output_schema=schema,
            use_json_mode=True,
            telemetry=False,
        )
        images = [Image(content=frame.jpeg, mime_type="image/jpeg") for frame in frames]
        try:
            run = await agent.arun(input=prompt, images=images)
        except Exception as error:
            logger.warning("vision read unavailable")
            raise AttributionError("vision_unavailable") from error
        finally:
            await http.aclose()
        await metering.record_model_run(self._model, run)
        if not isinstance(run.content, schema):
            logger.warning("vision read unusable")
            raise AttributionError("vision_unavailable")
        return run.content
