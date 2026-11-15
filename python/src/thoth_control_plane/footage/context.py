"""The context card: who and what a main post is about, read by a model from material the run
already has, and the matching that finds footage of the same story (footage library spec
2026-11-15, sections 4.1-4.3)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, Protocol

from pydantic import ConfigDict, Field, field_validator

from thoth_control_plane.acquisition.models import SourceReport
from thoth_control_plane.domain.models import StrictModel

MAX_COMMENTS = 25
MAX_TRANSCRIPT = 1500

CARD_PROMPT = """You read one social media post from Indonesia and write a context card used to find
footage of the same story on YouTube, TikTok and X. Return only JSON:
{"people": [{"name": str, "aliases": [str], "role": str, "accounts": [str]}],
 "event": str, "place": str, "when": str, "meme_or_joke": str,
 "queries": [str], "notes": str}
Rules: people are the real persons the story is about; aliases are every other name they go by
(nicknames, real names, spellings, labels used in comments). queries: up to 6 short searches as
Indonesian viewers would type them, each pairing a person's name or alias with the event or the
other person; no hashtags, no generic objects. Use the material and your general knowledge of
Indonesian public figures; put "?" after anything you are unsure of.
Queries are in the language of the post."""

REFINE_PROMPT = """You keep a context card used to find footage of one story. You get the card
and the titles and channels a first search returned. Return the same JSON shape as the card:
add every other name the titles use for the card's people (real names, spellings), correct the
people, event or place where the titles show the card is wrong, and set "queries" to at most 3
NEW short searches (not already in the card) that pair a person's name or alias with the event.
Ignore titles about other stories. Put "?" after anything you are unsure of."""


def _texts(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None and not isinstance(item, (dict, list))]


def _text(value: object) -> str:
    return "" if value is None or isinstance(value, (dict, list)) else str(value)


class CardPerson(StrictModel):
    # The model's JSON is untrusted: unknown keys are dropped and odd types become empty.
    model_config = ConfigDict(extra="ignore", strict=False)

    name: str = ""
    aliases: list[str] = Field(default_factory=list)
    role: str = ""
    accounts: list[str] = Field(default_factory=list)

    @field_validator("aliases", "accounts", mode="before")
    @classmethod
    def _lists(cls, value: object) -> list[str]:
        return _texts(value)

    @field_validator("name", "role", mode="before")
    @classmethod
    def _strings(cls, value: object) -> str:
        return _text(value)


class ContextCard(StrictModel):
    model_config = ConfigDict(extra="ignore", strict=False)

    people: list[CardPerson] = Field(default_factory=list)
    event: str = ""
    place: str = ""
    when: str = ""
    meme_or_joke: str = ""
    queries: list[str] = Field(default_factory=list)
    notes: str = ""

    @field_validator("people", mode="before")
    @classmethod
    def _people(cls, value: object) -> list[Any]:
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    @field_validator("queries", mode="before")
    @classmethod
    def _queries(cls, value: object) -> list[str]:
        return _texts(value)

    @field_validator("event", "place", "when", "meme_or_joke", "notes", mode="before")
    @classmethod
    def _strings(cls, value: object) -> str:
        return _text(value)


class CardModel(Protocol):
    async def card(self, system: str, material: str) -> ContextCard | None: ...


def card_material(main: SourceReport, figures: Sequence[dict[str, Any]], transcript: str) -> str:
    """What the card model reads: the post, the run's figures, the most-liked comments, and the
    start of the transcript."""
    comments = sorted(main.comments, key=lambda comment: -comment.likes)[:MAX_COMMENTS]
    return json.dumps(
        {
            "platform": main.source.platform,
            "owner": main.post.owner_handle,
            "published_at": main.post.published_at,
            "caption": main.post.text,
            "figures": list(figures),
            "comments": [{"text": c.text, "likes": c.likes} for c in comments],
            "transcript": transcript[:MAX_TRANSCRIPT],
        },
        ensure_ascii=False,
    )
