"""What the attribution service needs from the outside world; adapters implement it.

A port that cannot do its job raises `AttributionError`; a port about external content may raise
anything else, and the service degrades that evidence or candidate.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, get_args

from pydantic import BaseModel, Field, model_validator

from thoth_control_plane.acquisition.models import DiscoveredVideo, SourceReport
from thoth_control_plane.attribution.matching import TextBox
from thoth_control_plane.attribution.models import Platform

VisualKind = Literal["footage", "commentary", "unknown"]
ReactionShape = Literal[
    "none", "screenshot", "picture_in_picture", "green_screen", "split_screen", "clip_then_talk"
]
SubjectMedia = Literal["video", "text", "image", "none", "unknown"]
ShotLabel = Literal["creator", "subject", "both", "other"]
REACTION_SHAPES = frozenset(get_args(ReactionShape))
SUBJECT_MEDIA = frozenset(get_args(SubjectMedia))
SHOT_LABELS = frozenset(get_args(ShotLabel))
MAX_SHOWS = 6


class AttributionError(Exception):
    """A required tool, model, or provider could not do its job: never a degraded verdict.

    Operator, 2026-10-13: vision and Jev are required, and a failure is an explicit error that
    fails the workflow. External content (discovery, candidates) still degrades.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Frame:
    second: float
    jpeg: bytes = field(repr=False)


class CoverReading(BaseModel):
    """What the vision model reads off a cover: bounded prose, never a decision."""

    headline: str = Field(
        default="", max_length=300, description="Text printed on the image, verbatim; empty if none"
    )
    scene: str = Field(default="", max_length=300, description="One sentence: what the video shows")
    icon: str = Field(
        default="",
        max_length=200,
        description="Any app or platform logo you see and where it is; empty if none",
    )
    handles: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Every @username or account name printed on the image, exactly as written",
    )
    reaction_shape: ReactionShape = Field(
        default="none",
        description=(
            "none: an ordinary video; screenshot: a screenshot of another post fills the frame; "
            "picture_in_picture: a person in a small window over another video; green_screen: a "
            "person in front of another post or video; split_screen: two videos side by side or "
            "stacked; clip_then_talk: another video plays, then a person talks about it"
        ),
    )
    subject_media: SubjectMedia = Field(
        default="none",
        description="What the reacted-to post is: video, text, image; none when not a reaction",
    )
    shows: list[ShotLabel] = Field(
        default_factory=list,
        max_length=MAX_SHOWS,
        description=(
            "For each image in order: creator (the person making this video), subject (the "
            "other post or video), both, or other"
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _clip(cls, data: Any) -> Any:
        """A text-heavy cover is clipped, not rejected: the rest of the reading still counts."""
        if not isinstance(data, dict):
            return data
        clipped = dict(data)
        for name, limit in (("headline", 300), ("scene", 300), ("icon", 200), ("handles", 10)):
            if isinstance(clipped.get(name), str | list):
                clipped[name] = clipped[name][:limit]
        # An unknown value is coerced, never a rejected reading (models invent labels).
        if "reaction_shape" in clipped and clipped["reaction_shape"] not in REACTION_SHAPES:
            clipped["reaction_shape"] = "none"
        if "subject_media" in clipped and clipped["subject_media"] not in SUBJECT_MEDIA:
            clipped["subject_media"] = "unknown"
        if isinstance(clipped.get("shows"), list):
            clipped["shows"] = [
                label if label in SHOT_LABELS else "other" for label in clipped["shows"]
            ][:MAX_SHOWS]
        return clipped


class VisualClass(BaseModel):
    kind: VisualKind = Field(
        description=(
            "footage: raw footage of an event; commentary: a person talking about it, a news "
            "anchor, a slideshow, or a reaction; unknown: cannot tell"
        )
    )


@dataclass(frozen=True)
class Decisions:
    is_repost: float
    handle: str | None
    handle_probability: float
    platform: Platform | None
    platform_probability: float


@dataclass(frozen=True)
class Assessment:
    """Jev's answer: P(contribution >= new viewpoint), and P(comments discuss the creator)."""

    contribution: float
    discussion: float | None


@dataclass(frozen=True)
class AcquiredCandidate:
    candidate_id: str
    report: SourceReport
    video: Path | None


class FrameSource(Protocol):
    async def frames(
        self, video: Path, *, fps: float, seconds: float | None = None
    ) -> list[Frame]: ...


class VisualMatcher(Protocol):
    """Finds a candidate's footage inside repost frames, whatever the framing."""

    async def prepare(self, frames: Sequence[Frame]) -> Any:
        """Features of a video's sampled frames; falsy when no frame has usable detail."""
        ...

    async def compare(self, repost: Any, candidate: Any) -> list[int]:
        """For each sampled repost frame, the best inlier count against any candidate frame."""
        ...


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Transcript:
    language: str
    segments: tuple[Segment, ...] = ()


@dataclass(frozen=True)
class Turn:
    start: float
    end: float
    speaker: int


class Transcriber(Protocol):
    async def transcribe(self, video: Path, *, seconds: float) -> Transcript: ...


class Diarizer(Protocol):
    async def turns(self, video: Path, *, seconds: float) -> list[Turn]: ...


class SceneDetector(Protocol):
    async def cuts(self, video: Path) -> list[float]: ...


class TextReader(Protocol):
    async def read(self, frame: Frame) -> list[TextBox]: ...


class VisionReader(Protocol):
    async def read_cover(self, frames: Sequence[Frame]) -> CoverReading: ...

    async def classify(self, frames: Sequence[Frame]) -> VisualKind: ...


class DecisionModel(Protocol):
    async def decide(self, evidence: dict[str, object], handles: Sequence[str]) -> Decisions: ...


class Discoverer(Protocol):
    def supports(self, platform: Platform) -> bool: ...

    async def discover(self, platform: Platform, handle: str) -> list[DiscoveredVideo]: ...


class CandidateAcquirer(Protocol):
    async def acquire(self, candidate_id: str, url: str) -> AcquiredCandidate | None: ...

    async def discard(self, candidate_id: str) -> None: ...
