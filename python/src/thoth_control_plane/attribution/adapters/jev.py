"""Typed decisions from TypeSafe Jev through OpenRouter's Decisions API; never prose.

Jev answers typed questions about one state with calibrated probabilities: `noul` (a yes
probability) and `choice` (one of the declared options). The handle question only ever offers
handles the evidence contains, so the answer cannot invent an account.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any, TypeVar, get_args

import httpx

from thoth_control_plane.attribution.models import Platform
from thoth_control_plane.attribution.ports import AttributionError, Decisions

logger = logging.getLogger(__name__)

# OpenRouter only for now (operator, 2026-10-08); the request and answer shapes are
# the same as TypeSafe's own API.
JEV_URL = "https://openrouter.ai/api/alpha/decisions"
JEV_MODEL = "typesafe/jev-1.13"
TIMEOUT_SECONDS = 10.0
ATTEMPTS = 2
NONE_OPTION = "none"
IS_REPOST = (
    "Does this evidence show that the post re-uploads a video made by another account? "
    "Signs: a credit or watermark naming another username, a repost or 'credit' caption."
)
CREDITED_HANDLE = (
    "Which handle is credited as the original creator of the video? "
    "Choose none when no handle is credited as the source."
)
CREDITED_PLATFORM = (
    "On which platform was the credited original posted? Use the platform icon description, "
    "the watermark text, and the caption."
)
PLATFORM_OPTIONS = {
    "tiktok": "TikTok: a TikTok logo, a music note, or a TikTok watermark",
    "instagram": "Instagram: a camera or Reels logo, or an Instagram credit",
    "x": "X or Twitter: an X or bird logo",
    "youtube": "YouTube: a red play-button logo",
    "threads": "Threads: an @-shaped Threads logo",
    "unknown": "the evidence does not show the platform",
}
PLATFORMS: frozenset[str] = frozenset(get_args(Platform))
T = TypeVar("T")


class JevDecisionModel:
    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None) -> None:
        self._key = api_key
        self._client = client

    async def decide(self, evidence: dict[str, object], handles: Sequence[str]) -> Decisions:
        questions: dict[str, Any] = {
            "is_repost": {"type": "noul", "instructions": IS_REPOST},
            "credited_platform": {
                "type": "choice",
                "instructions": CREDITED_PLATFORM,
                "criteria": PLATFORM_OPTIONS,
            },
        }
        if handles:
            criteria = {
                handle: f"@{handle} is credited as the original creator" for handle in handles
            }
            criteria[NONE_OPTION] = "no handle is credited as the original creator"
            questions["credited_handle"] = {
                "type": "choice",
                "instructions": CREDITED_HANDLE,
                "criteria": criteria,
            }
        body = {"model": JEV_MODEL, "state": evidence, "questions": questions}
        return await self._ask(body, lambda answers: _parse(answers, handles))

    async def _ask(self, body: dict[str, Any], parse: Callable[[dict[str, Any]], T]) -> T:
        """One Decisions call, parsed, retried once on a transport or malformed answer;
        unavailable raises (operator, 2026-10-13: Jev is required)."""
        for attempt in range(ATTEMPTS):
            try:
                async with self._session() as client:
                    response = await client.post(
                        JEV_URL,
                        json=body,
                        headers={"Authorization": f"Bearer {self._key}"},
                        timeout=TIMEOUT_SECONDS,
                    )
                response.raise_for_status()
                return parse(response.json()["answers"])
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                if attempt + 1 == ATTEMPTS:
                    logger.warning("jev decision unavailable after retry; attribution stops")
        raise AttributionError("decision_unavailable")

    @contextlib.asynccontextmanager
    async def _session(self) -> AsyncIterator[httpx.AsyncClient]:
        if self._client is not None:
            yield self._client
            return
        async with httpx.AsyncClient() as client:
            yield client


def _parse(answers: dict[str, Any], handles: Sequence[str]) -> Decisions:
    is_repost = min(1.0, max(0.0, float(answers["is_repost"]["noul"])))
    platform_answer = answers["credited_platform"]
    platform = str(platform_answer["choice"])
    platform_probability = float(platform_answer["probabilities"][platform])
    handle: str | None = None
    handle_probability = 0.0
    handle_answer = answers.get("credited_handle")
    if handle_answer is not None:
        choice = str(handle_answer["choice"])
        if choice != NONE_OPTION and choice in handles:
            handle = choice
            handle_probability = float(handle_answer["probabilities"][choice])
    return Decisions(
        is_repost=is_repost,
        handle=handle,
        handle_probability=handle_probability,
        platform=platform if platform in PLATFORMS else None,  # type: ignore[arg-type]
        platform_probability=platform_probability,
    )
