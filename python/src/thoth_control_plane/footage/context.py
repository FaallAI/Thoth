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
from thoth_control_plane.footage.gates import mentions, norm
from thoth_control_plane.footage.models import FootageObject

MAX_COMMENTS = 25
MAX_TRANSCRIPT = 1500
MIN_NAME = 3  # "TG" or "RG" would match unrelated posts
MIN_TERM = 4
MAX_SPOKEN = 12
WINDOW_BEFORE = timedelta(days=30)
PERSON_WINDOW = timedelta(days=730)  # a clip naming the subject (spec 10.5)
DEFAULT_VISUAL = "the scene the post is about"
# Spec 10.4: a card searches its incident twice at most and up to 6 related events.
INCIDENT_QUERIES = 2
MAX_RELATED = 6
# Spec 10.12, revision 3: the vision prompt never carries a person's name.
PERSON_VISUAL = "a person on camera"

CARD_PROMPT = """You read one social media post from Indonesia and write a context card used to find
footage of this story's people and context on YouTube, TikTok and X. Return only JSON:
{"main_kind": "incident" | "commentary",
 "people": [{"name": str, "aliases": [str], "role": str, "accounts": [str]}],
 "event": str, "place": str, "when": str, "meme_or_joke": str,
 "queries": [str], "related": [{"event": str, "query": str}], "spoken": [str], "notes": str}
Rules: main_kind is "incident" when the video shows an event, an interaction or a person doing
something in person, and "commentary" when it is a person talking to camera (a monologue,
reaction, opinion or explainer) about an outside event, controversy or other public figures.
people are the real persons the story is about. people[0] is the person the post shows
doing the thing, even when only a nickname or a description is known ("pria bawa pedang"). A
person named only in comments is not one of the people, unless the comments say that person is
in the video. aliases are every other name they go by (nicknames, real names, other spellings,
labels used in comments, each name without titles ("Saiful" for "Master Saiful"), and the
hashtag form of each name: no spaces, lowercase). event and place are in the language of the
post (Indonesian for an Indonesian post), with real names of events, awards and institutions
capitalised and years kept as viewers say them ("Polemik kritik panggung Piala Citra FFI 2026
soal pernyataan Fadli Zon dan Kemenbud", never an English translation). spoken: up to
12 single lowercase Indonesian words people would say aloud when discussing this event (objects,
actions, feelings), never names. queries: at most 2 short searches
about this incident as Indonesian viewers would type them, each pairing a person's name or alias
with the event or the other person; no hashtags, no generic objects. related: up to 6 OTHER events
these people are known for or that followed (their shows, a clarification, an apology, a reply, a
meeting), each with one short search as Indonesian viewers would type it that names people[0];
never this incident itself.
On a "commentary" post: read the entire transcript from start to finish, not only its opening.
people[1:] lists every outside public figure named anywhere in the transcript or caption (not
only the account replied to: also each minister or figure cited in the argument), and queries
and related include each controversy, protest or gesture it cites. queries and related search
the specific outside events, moments, gestures and statements discussed, as Indonesian viewers
search them, without forcing people[0]'s name into them ("FFI 2026 3 jari", "Fadli Zon
menyangkal 1998"); each related event describes the visible scene a clip of it shows ("Sineas
mengacungkan tiga jari di panggung FFI 2026"), not an abstract claim. Use the material and your
general knowledge of Indonesian public figures; put "?" after anything you are unsure of.
Queries are in the language of the post."""

REFINE_PROMPT = """You keep a context card used to find footage of one story. You get the card
and the titles and channels a first search returned. Return the same JSON shape as the card:
keep people[0] first and add the real names the titles use for people[0], add every other name
the titles use for the card's people (real names, spellings), keep "spoken", correct the
people, event or place where the titles show the card is wrong (event and place stay in the
language of the post), keep "main_kind", and set "queries" to at most 3
NEW short searches (not already in the card) that pair a person's name or alias with the event.
You may add related events the titles show (same shape as the card's "related").
Add to people and related the key figures, award winners, films and protest gestures that the
titles repeat and the card misses ("Siera Tamihardja", "Para Perasuk", "salam 3 jari").
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


class RelatedEvent(StrictModel):
    """Another event the card's people are known for or that followed (spec 10.4)."""

    model_config = ConfigDict(extra="ignore", strict=False)

    event: str = ""
    query: str = ""

    @field_validator("event", "query", mode="before")
    @classmethod
    def _strings(cls, value: object) -> str:
        return _text(value)


class ContextCard(StrictModel):
    model_config = ConfigDict(extra="ignore", strict=False)

    # Spec 2026-11-26, 3.1: a talking-head post about outside events; old cards are incidents.
    main_kind: Literal["incident", "commentary"] = "incident"
    people: list[CardPerson] = Field(default_factory=list)
    event: str = ""
    place: str = ""
    when: str = ""
    meme_or_joke: str = ""
    queries: list[str] = Field(default_factory=list)
    related: list[RelatedEvent] = Field(default_factory=list)
    # Words people say aloud when discussing the event (spec 2026-11-15, 9.2).
    spoken: list[str] = Field(default_factory=list)
    notes: str = ""

    @field_validator("main_kind", mode="before")
    @classmethod
    def _kind(cls, value: object) -> str:
        return "commentary" if _text(value).strip().lower() == "commentary" else "incident"

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

    @field_validator("related", mode="before")
    @classmethod
    def _related(cls, value: object) -> list[Any]:
        if not isinstance(value, list):
            return []
        events = [RelatedEvent.model_validate(item) for item in value if isinstance(item, dict)]
        return [e for e in events if e.query.strip()][:MAX_RELATED]

    @field_validator("spoken", mode="before")
    @classmethod
    def _spoken(cls, value: object) -> list[str]:
        words = (word.strip().lower() for word in _texts(value))
        return list(dict.fromkeys(w for w in words if w and not any(c.isspace() for c in w)))[
            :MAX_SPOKEN
        ]

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


# Titles a name is said with; "Master Saiful" is also said "Saiful" (live wf_4ac021d9).
TITLES = frozenset(
    {"master", "bang", "abang", "pak", "bu", "mas", "mbak", "kak", "om", "tante", "ustadz", "habib"}
)


def _names(person: CardPerson) -> list[str]:
    found = [norm(text.replace("?", "")) for text in [person.name, *person.aliases]]
    bare = [
        " ".join(words[1:])
        for words in (n.split() for n in found)
        if words[:1] and words[0] in TITLES
    ]
    return [name for name in dict.fromkeys([*found, *bare]) if len(name) >= MIN_NAME]


def subject_names(card: ContextCard) -> list[str]:
    """The subject's (people[0]) name and aliases, normalised, longest first (spec 9.2)."""
    if not card.people:
        return []
    return sorted(dict.fromkeys(_names(card.people[0])), key=len, reverse=True)


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
        # Indonesian openers and generic nouns (spec 2026-11-26, 3.3).
        "tanggapan",
        "respons",
        "kritik",
        "soal",
        "tentang",
        "terkait",
        "berita",
        "kasus",
        "momen",
        "aksi",
        "polemik",
        "pernyataan",
        "panggung",
        "tahun",
        "hari",
        "orang",
        "warga",
        "publik",
        "pemerintah",
        "sosial",
    }
)
TOKEN = re.compile(r"[A-Za-z0-9]+")
_YEAR = re.compile(r"(?:19|20)\d{2}")


def _terms(text: str) -> set[str]:
    """Distinctive words: proper nouns of 4+ letters, acronyms of 3+ and years ("Urban", "USS",
    "2026"), never filler ("the", "while", "event", "tanggapan")."""
    terms = {
        token.lower()
        for token in TOKEN.findall(text)
        if (token.isupper() and len(token) >= MIN_NAME)
        or (token[0].isupper() and len(token) >= MIN_TERM)
        or _YEAR.fullmatch(token)
    }
    return {term for term in terms - GENERIC_TERMS if term in content_words(term)}


def event_terms(card: ContextCard) -> list[str]:
    """The event's and place's distinctive words."""
    return sorted(_terms(f"{card.event} {card.place}"))


def _event_match(matched: set[str], event_only: set[str]) -> bool:
    """Two matched terms, and a year never pairs with the place alone: "Konser Jakarta 2026" is
    not "Polemik FFI 2026" in Jakarta (spec 2026-11-26, 3.3)."""
    words = {term for term in matched if not _YEAR.fullmatch(term)}
    return len(matched) >= 2 and (len(words) >= 2 or bool(words & event_only))


def _says(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "


def _named_words(card: ContextCard) -> set[str]:
    # A person's name is no event word: "Denny Sumargo" alone is another person, not the event.
    return {word for name in card_names(card) for word in name.split()}


def discussed_names(card: ContextCard) -> list[str]:
    """The names and aliases of people[1:], the figures a commentary discusses."""
    return list(dict.fromkeys(name for person in card.people[1:] for name in _names(person)))


def related_terms(card: ContextCard) -> set[str]:
    return {term for r in card.related for term in _terms(r.event) | _terms(r.query)}


def has_event_term(text: str, card: ContextCard) -> bool:
    """Whether normalised `text` says a non-person event word of the card or its related events,
    as a whole word ("Ernest khusus" never says "USS")."""
    terms = (set(event_terms(card)) | related_terms(card)) - _named_words(card)
    return any(_says(text, term) for term in terms)


def names_discussed_with_context(said: str, card: ContextCard) -> bool:
    """On a commentary card: normalised `said` names a discussed figure and one context word
    (an event, related or query term, or a spoken word). "Fadli Zon bantah soal 1998" is on the
    story, "Fadli Zon kunjungi museum batik" is not (spec 2026-11-26, 3.3)."""
    if card.main_kind != "commentary":
        return False
    if not any(mentions(said, name) for name in discussed_names(card)):
        return False
    queries = {term for query in card.queries for term in _terms(query)}
    terms = (set(event_terms(card)) | related_terms(card) | queries) - _named_words(card)
    return any(_says(said, term) for term in terms | set(card.spoken))


def strip_names(text: str, card: ContextCard) -> str:
    """The text with every card name and alias replaced by "a person" (spec 10.12, revision 3)."""
    for name in card_names(card):
        words = r"\W+".join(re.escape(word) for word in name.split())
        text = re.sub(rf"(?i)(?<!\w){words}(?!\w)", "a person", text)
    return text


def _person(card: ContextCard, query: str) -> CardPerson | None:
    text = norm(query)
    return next((p for p in card.people if any(mentions(text, name) for name in _names(p))), None)


def names_subject(text: str, card: ContextCard) -> bool:
    """Whether normalised `text` names people[0] in any of its forms (spec 10.12, revision 1)."""
    return any(mentions(text, name) for name in subject_names(card))


def _is_commentator_only(query: str, card: ContextCard) -> bool:
    """A commentary query about people[0] alone: no discussed figure, no event word."""
    said = norm(query)
    return (
        names_subject(said, card)
        and not any(mentions(said, name) for name in discussed_names(card))
        and not has_event_term(said, card)
    )


def context_objects(
    card: ContextCard, queries: Sequence[str], related: Sequence[RelatedEvent] = ()
) -> list[FootageObject]:
    """One search per query; a query naming a person checks that a person is on screen. The
    visual never names anyone (spec 10.12). On a commentary card a query about a discussed
    figure or the event checks the event's scene, not any person (spec 2026-11-27 ocr video
    credit, 3.4)."""
    objects: list[FootageObject] = []
    asked = [(query, None) for query in queries] + [(r.query, r) for r in related]
    for query, event in asked:
        if not norm(query):
            continue
        person = _person(card, query) is not None
        if event is not None:
            visual = strip_names(event.event, card) or DEFAULT_VISUAL
        elif person and (card.main_kind != "commentary" or _is_commentator_only(query, card)):
            visual = PERSON_VISUAL
        else:
            visual = strip_names(card.event, card) or DEFAULT_VISUAL
        objects.append(
            FootageObject(
                query=query.strip()[:100],
                visual=" ".join(visual.split())[:300] or DEFAULT_VISUAL,
                person=person,
            )
        )
    return objects


def card_objects(card: ContextCard) -> list[FootageObject]:
    """Round one's searches: up to 2 about the incident, then the related events (spec 10.4)."""
    return context_objects(card, card.queries[:INCIDENT_QUERIES], card.related)


def _when(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def in_window(
    published_at: str | None,
    main_published: str | None,
    now: datetime,
    before: timedelta = WINDOW_BEFORE,
) -> bool:
    """From `before` the main post (30 days by default) to the run; an unknown time stays in."""
    when = _when(published_at)
    if when is None:
        return True
    main = _when(main_published)
    return (main is None or when >= main - before) and when <= now


def context_reason(text: str, card: ContextCard) -> Literal["story"] | None:
    """None when the text names the subject, or two event terms, as whole words. A clip naming
    only another card person is off the story (spec 10.12, revision 1). A commentary card also
    takes two terms of one related event, or a discussed figure with a context word (spec
    2026-11-26, 3.3). On a commentary card an event match naming nobody also needs a topic word
    or three terms, so a generic event vlog is off the story (spec 2026-11-27 ocr video credit,
    3.4)."""
    said = norm(text)
    if names_subject(said, card):
        return None
    commentary = card.main_kind == "commentary"
    if commentary and names_discussed_with_context(said, card):
        return None
    signals = _topic_signals(card) if commentary else set()
    named = _named_words(card)
    matched = {term for term in event_terms(card) if term not in named and _says(said, term)}
    if _event_match(matched, _terms(card.event) - named) and _commentary_event_ok(
        said, matched, signals
    ):
        return None
    if commentary:
        for related in card.related:
            hits = {term for term in _terms(related.event) - named if _says(said, term)}
            if (
                len(hits) >= 2
                and any(not _YEAR.fullmatch(term) for term in hits)
                and _commentary_event_ok(said, hits, signals)
            ):
                return None
    return "story"


def _topic_signals(card: ContextCard) -> set[str]:
    """The words of the controversy a commentary card is about: its spoken words and its
    queries' words that are no name and no event term ("kritik", "protes", "jari")."""
    named = _named_words(card)
    terms = set(event_terms(card))
    texts = (*card.queries, *(r.query for r in card.related))
    words = {word for text in texts for word in content_words(text)}
    return set(card.spoken) | (words - named - terms - {"indonesia", "indonesian"})


def _commentary_event_ok(said: str, matched: set[str], signals: set[str]) -> bool:
    """A personless event match on a commentary card: a topic word, or three matched terms with
    two that are no year ("Piala Citra FFI 2026")."""
    if not signals:
        return True
    words = {term for term in matched if not _YEAR.fullmatch(term)}
    return (len(matched) >= 3 and len(words) >= 2) or any(_says(said, w) for w in signals)


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
    return _event_match(now & then, _terms(card.event) - words)
