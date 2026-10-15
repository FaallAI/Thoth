"""Footage queries through Agno over OpenRouter's OpenAI-compatible endpoint."""

from __future__ import annotations

import logging

from thoth_control_plane.footage.queries import FootageQueryAnswer

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
TIMEOUT_SECONDS = 60.0


class AgnoQueryModel:
    def __init__(self, api_key: str, model: str, *, base_url: str = OPENROUTER_BASE_URL) -> None:
        self._key = api_key
        self._model = model
        self._base_url = base_url

    async def read(self, prompt: str) -> FootageQueryAnswer | None:
        from agno.agent import Agent
        from agno.models.openai.like import OpenAILike

        agent = Agent(
            model=OpenAILike(
                id=self._model,
                api_key=self._key,
                base_url=self._base_url,
                timeout=TIMEOUT_SECONDS,
                max_retries=1,
                temperature=0.0,
            ),
            output_schema=FootageQueryAnswer,
            use_json_mode=True,
            telemetry=False,
        )
        try:
            run = await agent.arun(input=prompt)
        except Exception:
            logger.warning("footage queries unavailable")
            return None
        return run.content if isinstance(run.content, FootageQueryAnswer) else None
