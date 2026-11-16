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
# A person query: the rule is part of the definition of kind, not an appendix. It names nobody,
# so the description cannot parrot a name (spec 10.12, revision 3).
_PERSON_KIND = (
    "is it footage or commentary? The video showing a real person themself speaking or acting "
    "on camera (at an event, a press conference, a visit, or an interview they give) is "
    "footage; a news anchor, a slideshow, still photos, or a reaction is commentary."
)
FOOTAGE_PROMPT = _PROMPT.replace("{kind}", _KIND)
PERSON_PROMPT = _PROMPT.replace("{kind}", _PERSON_KIND)
# Spec 10.5/10.12: one frame of the main goes first, and the same call says whether the clip
# shows that scene.
_SCENE = (
    "The first image is one frame of another video; the other images are frames of the short "
    "video. "
)
_SCENE_QUESTION = (
    "same_event: do the frames of the short video show the same scene and moment as the first "
    "image? Answer yes or no. "
)


class FootageAnswer(BaseModel):
    kind: Literal["footage", "commentary"] = Field(description="footage or commentary")
    shows_object: Literal["yes", "partly", "no"]
    description: str = ""
    same_event: Literal["yes", "no"] = "no"

    @field_validator("description", mode="before")
    @classmethod
    def _bounded(cls, value: object) -> object:
        return ("" if value is None else str(value)).strip()[:300]


class AgnoFootageJudge(AgnoVisionReader):
    async def judge(
        self,
        frames: Sequence[Frame],
        visual: str,
        *,
        person: bool = False,
        reference: Frame | None = None,
    ) -> FootageAnswer:
        """Raises `AttributionError("vision_unavailable")` on a provider error or a bad answer.
        With `reference` (a frame of the main), it also answers `same_event`."""
        template = PERSON_PROMPT if person else FOOTAGE_PROMPT
        prompt = template.format(visual=" ".join(visual.split())[:300])
        if reference is None:
            return await self._run(FootageAnswer, prompt, frames[:MAX_FRAMES])
        prompt = _SCENE + prompt.replace("Answer three things.", "Answer four things.").replace(
            "description:", _SCENE_QUESTION + "description:"
        )
        return await self._run(FootageAnswer, prompt, [reference, *frames[:MAX_FRAMES]])
