"""The planner's one vision call per draft (spec 2026-11-13, 5.4), on OpenRouter.

Raw httpx rather than Agno (as `attribution/adapters/vision.py` uses): the trial showed the call
needs `reasoning`, the `provider` data policy and `finish_reason`, which Agno hides. A shared
provider pool answers 429 often, so busy answers are retried; a failed model hands over to the
fallback once, and that hand-over is logged so it can be watched (operator, 2026-11-13).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from thoth_control_plane import metering
from thoth_control_plane.assembly.planner_shots import Sheet

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
TIMEOUT_SECONDS = 120.0
ATTEMPTS = 3
BACKOFF_SECONDS = (5.0, 15.0)
BUSY = frozenset({429, 502, 503})
MAX_BASE = 3

#: Prompt v3 of the trial (2026-11-13), word for word (re-wrapped): the rules the judging taught.
SYSTEM_PROMPT = """\
You choose what to show under each narration phrase of an Indonesian news short video (9:16).
Candidates are the numbered video shots (S12) on the source sheets and the draft's cards (C3) on
the CARDS sheet:
comment cards (real social-media comments) and post cards (the post that reported the news).
Each phrase gets two layers:
- base: the video shots that fill the screen, best first (up to 3, in time order when they
  continue one moment);
- overlay: an optional card shown on top of the base (at most 1).

Rules, from the editor who judges this:
1. Soundbite first. When the main video's speech ("WHAT THE MAIN VIDEO SAYS") contains the
   phrase's statement or its key
   words, the base is the shot(s) where that sentence is spoken, not a card and not the shot
   before it.
2. The picture decides everything else: the person, event, place or action must be visible and
   plain at phone size.
   Small text (tickers, lower thirds, watermarks, channel headings) does not count.
3. A statue, poster or cardboard cutout is not the person. But when the story is about people
   meeting a cutout
   (a social experiment), shots of people meeting the cutout DO show "bertemu (langsung) dengan
   <person>".
   A phrase about the person himself ("sosok <person>", what he thinks) takes shots where he
   himself appears or speaks;
   if he never appears, the experiment's reaction shots.
4. Netizen, comment or "ada yang bilang/menyuruh" phrases: the overlay is the comment card whose
   text says that thing.
   The base is the main-video moment where people say or show the same reaction, if there is
   one; otherwise base is
   empty and the card fills the screen.
5. News-report phrases ("ada kabar", "beredar", "diunggah", "dibagikan"): overlay the post card
   when there is one.
   Never let the post card replace a soundbite (rule 1).
6. Closing or summary lines ("momen ini jadi bukti ...", "betapa beragamnya suara/pandangan
   publik") take the strongest
   reaction shots from the main video as base.
7. An empty or quiet place (empty palace, gate, street) does not show that something happened
   there. Pure mood or filler
   lines ("kita lihat saja nanti", "tegang", metaphors like "main game politik") need a picture
   that really shows it;
   otherwise answer none.
8. Prefer clean footage over clips that carry a big heading or another channel's frame.
9. "none" (empty base and empty overlay) is right whenever nothing shows the phrase; the editor
   falls back to the main video.

For every phrase answer:
- base: list of S ids; overlay: list with at most one C id;
- fit: "shows" or "none" (none only when both lists are empty);
- why: one short sentence in Indonesian naming what is visible, or what is missing.
Return JSON only: {"phrases": [{"id": "P1", "base": ["S3"], "overlay": ["C2"], "fit": "shows",
"why": "..."}]}"""


@dataclass(frozen=True)
class PhraseAsk:
    phrase_id: str
    beat: str
    text: str


@dataclass(frozen=True)
class PhraseAnswer:
    phrase_id: str
    base: list[str]
    overlay: str | None
    why: str


class PlannerUnavailable(Exception):
    """No model gave a usable answer; the planner keeps soundbites and the rhythm."""


class _Failed(Exception):
    def __init__(self, busy: bool) -> None:
        super().__init__("busy" if busy else "failed")
        self.busy = busy


def _image(jpeg: bytes) -> dict[str, Any]:
    url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()
    return {"type": "image_url", "image_url": {"url": url}}


def _content(
    sources: str,
    sheets: Sequence[Sheet],
    cards: bytes | None,
    script: str,
    phrases: Sequence[PhraseAsk],
) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = [{"type": "text", "text": sources}]
    for number, sheet in enumerate(sheets, start=1):
        label = f"Sheet {number} (source {sheet.source}): shots {', '.join(sheet.shot_ids)}"
        parts += [{"type": "text", "text": label}, _image(sheet.jpeg)]
    if cards is not None:
        parts += [{"type": "text", "text": "Sheet CARDS: the draft's cards"}, _image(cards)]
    lines = "\n".join(f"{p.phrase_id} [{p.beat}]: {p.text}" for p in phrases)
    text = f"FULL NARRATION (context):\n{script}\n\nPHRASES TO MATCH:\n{lines}"
    parts.append({"type": "text", "text": text})
    return parts


def _clamp(
    raw: dict[str, Any], asked: set[str], shot_ids: set[str], card_ids: set[str]
) -> list[PhraseAnswer]:
    """Only asked phrases, known ids, three base shots and one card: a model's word is checked."""
    answers = []
    for item in raw.get("phrases") or []:
        if not isinstance(item, dict) or item.get("id") not in asked:
            continue
        none = item.get("fit") == "none"
        base = [] if none else [s for s in item.get("base") or [] if s in shot_ids][:MAX_BASE]
        cards = [] if none else [c for c in item.get("overlay") or [] if c in card_ids]
        answers.append(
            PhraseAnswer(item["id"], base, cards[0] if cards else None, str(item.get("why") or ""))
        )
    return answers


class PlannerModel:
    def __init__(
        self,
        api_key: str,
        model: str,
        fallback: str | None,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        base_url: str = OPENROUTER_BASE_URL,
    ) -> None:
        self._key = api_key
        self._models = [model, *([fallback] if fallback and fallback != model else [])]
        self._client = client
        self._sleep = sleep
        self._base_url = base_url
        #: The model that answered the last call.
        self.model_used: str | None = None

    async def ask(
        self,
        sources: str,
        sheets: Sequence[Sheet],
        cards: bytes | None,
        script: str,
        phrases: Sequence[PhraseAsk],
        shot_ids: set[str],
        card_ids: set[str],
    ) -> list[PhraseAnswer]:
        content = _content(sources, sheets, cards, script, phrases)
        asked = {p.phrase_id for p in phrases}
        client = self._client or httpx.AsyncClient(timeout=TIMEOUT_SECONDS)
        try:
            for index, model in enumerate(self._models):
                if index:
                    logger.warning("planner fallback model used model=%s", model)
                raw = await self._answer(client, model, content)
                if raw is not None:
                    self.model_used = model
                    return _clamp(raw, asked, shot_ids, card_ids)
        finally:
            if self._client is None:
                await client.aclose()
        raise PlannerUnavailable()

    async def _answer(
        self, client: httpx.AsyncClient, model: str, content: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        for attempt in range(ATTEMPTS):
            try:
                return await self._once(client, model, content)
            except _Failed as failed:
                if not failed.busy:
                    return None
                logger.warning("planner model busy model=%s attempt=%d", model, attempt + 1)
                if attempt < ATTEMPTS - 1:
                    await self._sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
        return None

    async def _once(
        self, client: httpx.AsyncClient, model: str, content: list[dict[str, Any]]
    ) -> dict[str, Any]:
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": 12000,
            "temperature": 0,
            "usage": {"include": True},
            "reasoning": {"effort": "low"},
            "provider": {"data_collection": "deny"},
        }
        try:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {self._key}"},
                timeout=TIMEOUT_SECONDS,
            )
        except httpx.TransportError as error:
            raise _Failed(busy=True) from error
        if response.status_code in BUSY:
            raise _Failed(busy=True)
        if response.status_code != 200:
            logger.warning("planner model refused model=%s status=%d", model, response.status_code)
            raise _Failed(busy=False)
        try:
            data = response.json()
            choice = data["choices"][0]
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise _Failed(busy=False) from error
        usage = data.get("usage") or {}
        await metering.record_call(
            model, tokens_in=usage.get("prompt_tokens"), tokens_out=usage.get("completion_tokens")
        )
        finish = choice.get("finish_reason")
        if finish != "stop":
            logger.warning("planner answer cut off model=%s finish=%s", model, finish)
            raise _Failed(busy=False)
        text = (choice.get("message") or {}).get("content") or ""
        try:
            parsed = json.loads(text[text.find("{") : text.rfind("}") + 1])
        except ValueError as error:
            raise _Failed(busy=False) from error
        if not isinstance(parsed, dict):
            raise _Failed(busy=False)
        return parsed
