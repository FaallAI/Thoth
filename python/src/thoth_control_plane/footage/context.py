"""The context card: who and what a main post is about, read by a model from material the run
already has, and the matching that finds footage of the same story (footage library spec
2026-11-15, sections 4.1-4.3)."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, Literal, Protocol

from pydantic import ConfigDict, Field, field_validator

from thoth_control_plane.acquisition.models import SourceReport
from thoth_control_plane.domain.models import StrictModel
from thoth_control_plane.domain.planner import content_words
from thoth_control_plane.footage.gates import norm
from thoth_control_plane.footage.models import FootageObject

MAX_COMMENTS = 25
MAX_TRANSCRIPT = 1500
MIN_NAME = 3  # "TG" or "RG" would match unrelated posts
MIN_TERM = 4
WINDOW_BEFORE = timedelta(days=30)
DEFAULT_VISUAL = "the scene the post is about"

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
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, (dict, CardPerson))]

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


def _names(person: CardPerson) -> list[str]:
    found = (norm(text.replace("?", "")) for text in [person.name, *person.aliases])
    return [name for name in found if len(name) >= MIN_NAME]


def card_names(card: ContextCard) -> list[str]:
    """Every person's name and alias, normalised, at least 3 characters, longest first."""
    names = dict.fromkeys(name for person in card.people for name in _names(person))
    return sorted(names, key=len, reverse=True)


# Capitalised words a card's English event text starts sentences or names generic groups with.
GENERIC_TERMS = frozenset(
    {
        "after",
        "before",
        "while",
        "during",
        "with",
        "from",
        "this",
        "that",
        "their",
        "there",
        "about",
        "event",
        "area",
        "video",
        "viral",
        "indonesia",
        "indonesian",
        "national",
        "team",
        "player",
        "players",
        "people",
        "netizen",
        "netizens",
        "public",
        "local",
        "social",
        "media",
    }
)
TOKEN = re.compile(r"[A-Za-z0-9]+")


def event_terms(card: ContextCard) -> list[str]:
    """The event's and place's distinctive words: proper nouns of 4+ letters and acronyms of 3+
    ("Urban", "Sneaker", "USS", "Melbourne"), never filler ("the", "while", "event")."""
    tokens = TOKEN.findall(f"{card.event} {card.place}")
    terms = {
        token.lower()
        for token in tokens
        if (token.isupper() and len(token) >= MIN_NAME)
        or (token[0].isupper() and len(token) >= MIN_TERM)
    }
    return sorted(term for term in terms - GENERIC_TERMS if term in content_words(term))


def _says(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "


def context_objects(card: ContextCard, queries: Sequence[str]) -> list[FootageObject]:
    """One search per query; a query naming a person checks that person on screen."""
    objects: list[FootageObject] = []
    for query in queries:
        text = norm(query)
        if not text:
            continue
        person = next(
            (p for p in card.people if any(_says(text, name) for name in _names(p))), None
        )
        if person is not None:
            visual = f"{person.name.replace('?', '').strip()} in person, at {card.event}"
        else:
            visual = card.event or DEFAULT_VISUAL
        objects.append(
            FootageObject(
                query=query.strip()[:100],
                visual=" ".join(visual.split())[:300] or DEFAULT_VISUAL,
                person=person is not None,
            )
        )
    return objects


def _when(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def in_window(published_at: str | None, main_published: str | None, now: datetime) -> bool:
    """From 30 days before the main post to the run; an unknown time stays in."""
    when = _when(published_at)
    if when is None:
        return True
    main = _when(main_published)
    return (main is None or when >= main - WINDOW_BEFORE) and when <= now


def context_reason(text: str, card: ContextCard) -> Literal["story"] | None:
    """None when the text names a card person, or two event terms, as whole words."""
    said = norm(text)
    if any(_says(said, name) for name in card_names(card)):
        return None
    if sum(_says(said, term) for term in event_terms(card)) >= 2:
        return None
    return "story"


def same_event(card: ContextCard, event: str, names: Sequence[str]) -> bool:
    """A stored clip belongs to this card's story when two of the card's people are among its
    names, or one is and they share two distinctive event words. A person counts once, whatever
    their aliases, and people's own words are no event words: one person appears in many
    stories, a pair rarely (operator, 2026-11-15)."""
    stored = set(names)
    people = sum(1 for person in card.people if stored & set(_names(person)))
    if people >= 2:
        return True
    if people == 0:
        return False
    words = {word for name in [*card_names(card), *names] for word in name.split()}
    now = set(event_terms(card)) - words
    then = set(event_terms(ContextCard(event=event))) - words
    return len(now & then) >= 2
