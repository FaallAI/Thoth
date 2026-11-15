"""The context card model over OpenRouter's chat endpoint, raw httpx like the planner: the next
model on any failure, None when none answers (footage library spec 2026-11-15, 4.1)."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence

import httpx
from pydantic import ValidationError

from thoth_control_plane import metering
from thoth_control_plane.footage.context import ContextCard

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
TIMEOUT_SECONDS = 60.0
MAX_TOKENS = 1500


class OpenRouterCardModel:
    def __init__(
        self,
        api_key: str,
        models: Sequence[str],
        *,
        client: httpx.AsyncClient | None = None,
        base_url: str = OPENROUTER_BASE_URL,
    ) -> None:
        self._key = api_key
        self._models = list(dict.fromkeys(m for m in models if m))
        self._client = client
        self._base_url = base_url

    async def card(self, system: str, material: str) -> ContextCard | None:
        client = self._client or httpx.AsyncClient(timeout=TIMEOUT_SECONDS)
        try:
            for index, model in enumerate(self._models):
                if index:
                    logger.warning("footage card fallback model used model=%s", model)
                answer = await self._once(client, model, system, material)
                if answer is not None:
                    return answer
        finally:
            if self._client is None:
                await client.aclose()
        logger.warning("footage card unavailable")
        return None

    async def _once(
        self, client: httpx.AsyncClient, model: str, system: str, material: str
    ) -> ContextCard | None:
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": material},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": MAX_TOKENS,
            "temperature": 0,
            "usage": {"include": True},
            "provider": {"data_collection": "deny"},
        }
        try:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {self._key}"},
                timeout=TIMEOUT_SECONDS,
            )
            data = response.json() if response.status_code == 200 else None
            if data is None:
                logger.warning(
                    "footage card refused model=%s status=%d", model, response.status_code
                )
                return None
            usage = data.get("usage") or {}
            await metering.record_call(
                model,
                tokens_in=usage.get("prompt_tokens"),
                tokens_out=usage.get("completion_tokens"),
            )
            text = (data["choices"][0].get("message") or {}).get("content") or ""
            parsed = json.loads(text[text.find("{") : text.rfind("}") + 1])
            return ContextCard.model_validate(parsed)
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, ValidationError):
            logger.warning("footage card answer unusable model=%s", model)
            return None
