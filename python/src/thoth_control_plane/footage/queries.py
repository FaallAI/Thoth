"""Footage queries: a port of Scout's footage_objects prompt (rules unchanged, in English),
with one change: each object carries an English visual description for the vision check."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, Field, field_validator

from thoth_control_plane.footage.gates import compose_query
from thoth_control_plane.footage.models import FootageObject

MAX_OBJECTS = 4
MAX_NAME = 40
PROMPT = """From the post text below, extract entities for FOOTAGE (b-roll) search queries:
clips that could be SHOWN in a video. Split them into SUBJECTS (anchors) and OBJECTS (concrete
things).

RULES:
1. SUBJECTS = the core anchor entities of the topic: a brand, organization, title, place, or
   event (for example "nvidia", "cerita lila", "gempa filipina", "mindanao"). 1-3 only, the most
   central first.
2. OBJECTS = concrete THINGS, PRODUCTS, PLACES, or ACTIVITIES shown or implied (for example
   "chip ai", "data center", "kartu grafis", "longsor", "bioskop"). Do NOT attach the subject;
   keep them GENERIC, the subject is joined automatically when searching. Distinctive names
   ("mvp pictures", "m block space") may stay as they are. EXPAND generic brands: "ojol" to
   gojek, grab; "e-commerce" to shopee, tokopedia; "mobil sport" to porsche, ferrari. 2-4
   objects, the most visual first, short (1-4 words), lowercase, in the post's language, no
   duplicates.
3. For each object, "visual": one English sentence describing what it looks like on screen
   (for example "a green-jacketed motorbike taxi driver on a city street").
4. AVOID abstract things (payments, prices, policies, numbers) and the uploading or curating
   account.

TEXT:
[DESCRIPTION/CAPTION]: {description}
[HEADLINE/HOOK]: {headline}
[AUDIENCE COMMENTS]: {comments}

Answer in JSON: {{"subjects": [""], "objects": [{{"name": "", "visual": ""}}]}}"""


class ObjectItem(BaseModel):
    name: str = ""
    visual: str = ""

    @field_validator("name", "visual", mode="before")
    @classmethod
    def _null_is_empty(cls, value: object) -> object:
        return "" if value is None else value


class FootageQueryAnswer(BaseModel):
    subjects: list[str] = Field(default_factory=list)
    objects: list[ObjectItem | None] = Field(default_factory=list)

    @field_validator("subjects", "objects", mode="before")
    @classmethod
    def _null_is_empty_list(cls, value: object) -> object:
        return [] if value is None else value

    @field_validator("subjects", mode="before")
    @classmethod
    def _strings(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return [str(item) for item in value if item is not None]


def query_prompt(description: str, headline: str, comments: str) -> str | None:
    description, headline, comments = description.strip(), headline.strip(), comments.strip()
    if not (description or headline or comments):
        return None
    return PROMPT.format(
        description=description[:700] or "(empty)",
        headline=headline[:300] or "(empty)",
        comments=comments[:600] or "(empty)",
    )


def _clean(text: str) -> str:
    return " ".join(text.lower().split())


def footage_objects(answer: FootageQueryAnswer) -> list[FootageObject]:
    """Scout's clean(): lowercase, trim, at most 40 characters, no duplicates; then compose."""
    subjects = [s for s in (_clean(item) for item in answer.subjects) if s and len(s) <= MAX_NAME]
    subject = subjects[0] if subjects else ""
    seen: set[str] = set()
    objects: list[FootageObject] = []
    for item in answer.objects:
        if item is None:
            continue
        name, visual = _clean(item.name), " ".join(item.visual.split())
        if not name or len(name) > MAX_NAME or name in seen or not visual:
            continue
        seen.add(name)
        objects.append(FootageObject(query=compose_query(name, subject)[:100], visual=visual[:300]))
        if len(objects) == MAX_OBJECTS:
            break
    return objects


def top_comments(comments: Iterable[tuple[str, int]], limit: int = 12) -> str:
    """Scout's topComments: by likes, non-empty, joined with a bullet, at most 600 characters."""
    ranked = sorted(comments, key=lambda item: -item[1])
    texts = [text.strip() for text, _ in ranked if text.strip()][:limit]
    return " • ".join(texts)[:600]
