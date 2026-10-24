"""The comment judge on TypeSafe Jev through OpenRouter's Decisions API (spec 2026-10-24, D2).

One call per content set: the post and the comments are the state, and every comment gets its
own `noul` question, answered in parallel. Unlike attribution, a missing answer is not an error
here: the caller falls back to the noise check, so this never raises.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import httpx

from thoth_control_plane import metering
from thoth_control_plane.attribution.adapters.jev import ATTEMPTS, JEV_MODEL, JEV_URL

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 15.0
QUESTION = (
    "Is comment {key} in the state relevant to the post's topic, and does it say something: "
    "an opinion, a fact, a question, a reaction with content, or added context?"
)
CRITERIA = {
    "true": "it is about the post's topic and carries an opinion, fact, question, or reaction",
    "false": (
        "it is about something else (promotion, spam, unrelated chatter), or it is an empty "
        "reaction, a greeting, a tag of friends, or a one-word agreement"
    ),
}


class JevCommentJudge:
    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None) -> None:
        self._key = api_key
        self._client = client

    async def keep_probabilities(
        self, post: str, headline: str, comments: Sequence[str]
    ) -> list[float] | None:
        keys = [f"c{index}" for index in range(len(comments))]
        body = {
            "model": JEV_MODEL,
            "state": {
                "post": post[:1_500],
                "headline": headline[:300],
                "comments": dict(zip(keys, comments, strict=True)),
            },
            "questions": {
                key: {
                    "type": "noul",
                    "instructions": QUESTION.format(key=key),
                    "criteria": CRITERIA,
                }
                for key in keys
            },
        }
        for _ in range(ATTEMPTS):
            try:
                payload = await self._post(body)
                answers = payload["answers"]
                probabilities = [min(1.0, max(0.0, float(answers[key]["noul"]))) for key in keys]
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                continue
            usage = payload.get("usage") or {}
            await metering.record_call(
                JEV_MODEL,
                tokens_in=usage.get("input_tokens"),
                tokens_out=usage.get("output_tokens"),
            )
            return probabilities
        logger.warning("comment judge call failed after retry")
        return None

    async def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._key}"}
        if self._client is not None:
            response = await self._client.post(
                JEV_URL, json=body, headers=headers, timeout=TIMEOUT_SECONDS
            )
        else:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    JEV_URL, json=body, headers=headers, timeout=TIMEOUT_SECONDS
                )
        response.raise_for_status()
        return response.json()
