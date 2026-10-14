"""Who the post is about: a port of Scout's `extract_figures` prompt and normalization.

The model proposes names and types; code trims, drops empty names, maps an unknown type to
`person` (as Scout does), and keeps at most five.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field, field_validator

from thoth_control_plane.assembly.models import MAX_FIGURES, Figure

TYPES = ("person", "organization", "community")
PROMPT = """From the topic text below, identify the MAIN FIGURES being discussed: a specific,
publicly known PERSON, ORGANIZATION, or COMMUNITY.

RULES:
- Only those that are truly the subject of the discussion, not something mentioned in passing,
  a location, or a brand seen in the footage.
- Do NOT include the uploading or curating account (for example a reels or news account) unless
  it is the subject.
- If there is no specific figure, organization, or community (for example a story about an
  ordinary anonymous person), return an empty list.
- "type" is one of: person | organization | community.

TEXT:
[TITLE]: {title}
[DESCRIPTION]: {description}
[HEADLINE]: {headline}
[FOOTAGE]: {footage}

Answer in JSON: {{"figures": [{{"name": "", "type": "", "role": "short title or role",
"description": "one sentence of context"}}]}}"""


class FigureItem(BaseModel):
    name: str = ""
    type: str = ""
    role: str = ""
    description: str = ""

    @field_validator("name", "type", "role", "description", mode="before")
    @classmethod
    def _null_is_empty(cls, value: object) -> object:
        # Scout coerced with `String(f.role || '')`: a null field must not lose the answer.
        return "" if value is None else value


class FigureAnswer(BaseModel):
    figures: list[FigureItem] = Field(default_factory=list)


def figure_prompt(
    title: str, description: str, headline: str, footage: Sequence[str] = ()
) -> str | None:
    title, description, headline = title.strip(), description.strip(), headline.strip()
    if not (title or description or headline):
        return None
    shown = " ".join(item.strip() for item in footage if item.strip())
    return PROMPT.format(
        title=title[:200] or "(empty)",
        description=description[:600] or "(empty)",
        headline=headline[:200] or "(empty)",
        footage=shown[:600] or "(empty)",
    )


def normalize_figures(answer: FigureAnswer) -> list[Figure]:
    figures: list[Figure] = []
    for item in answer.figures:
        name = item.name.strip()[:120]
        if not name:
            continue
        kind = item.type.strip().lower()
        figures.append(
            Figure(
                name=name,
                type=kind if kind in TYPES else "person",  # type: ignore[arg-type]
                role=item.role.strip()[:200],
                description=item.description.strip()[:300],
            )
        )
        if len(figures) == MAX_FIGURES:
            break
    return figures
