"""The footage frame check: one structured vision call through Stage 4's reader."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from thoth_control_plane.attribution.adapters.vision import MAX_FRAMES, AgnoVisionReader
from thoth_control_plane.attribution.ports import Frame

_PROMPT = (
    "These are frames of a short video. Answer three things. kind: {kind} "
    'shows_object: do the frames show this: "{visual}"? '
    "Answer yes, partly, or no. description: one sentence on what the video shows. Answer in "
    "JSON."
)
_KIND = (
    "is it raw footage of an event, place, or thing, or commentary (a person talking to the "
    "camera about it, a news anchor, a slideshow, or a reaction)?"
)
# The visual names a person: the rule is part of the definition of kind, not an appendix.
_PERSON_KIND = (
    "is it footage or commentary? When the visual names a person, the video showing that "
    "person themself speaking (at an event, a press conference, a visit, or an interview they "
    "give) is footage; it is commentary only when someone else talks about them, or it is a "
    "news anchor, a slideshow, or a reaction."
)
FOOTAGE_PROMPT = _PROMPT.replace("{kind}", _KIND)
PERSON_PROMPT = _PROMPT.replace("{kind}", _PERSON_KIND)


class FootageAnswer(BaseModel):
    kind: Literal["footage", "commentary"] = Field(description="footage or commentary")
    shows_object: Literal["yes", "partly", "no"]
    description: str = ""

    @field_validator("description", mode="before")
    @classmethod
    def _bounded(cls, value: object) -> object:
        return ("" if value is None else str(value)).strip()[:300]


class AgnoFootageJudge(AgnoVisionReader):
    async def judge(
        self, frames: Sequence[Frame], visual: str, *, person: bool = False
    ) -> FootageAnswer:
        """Raises `AttributionError("vision_unavailable")` on a provider error or a bad answer."""
        template = PERSON_PROMPT if person else FOOTAGE_PROMPT
        prompt = template.format(visual=" ".join(visual.split())[:300])
        return await self._run(FootageAnswer, prompt, frames[:MAX_FRAMES])
