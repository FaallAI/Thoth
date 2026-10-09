"""What the attribution service needs from the outside world; adapters implement it.

Every port may fail. The service treats a raised exception as "this piece of evidence or this
candidate is unavailable" and never lets it fail the attribution.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from thoth_control_plane.acquisition.models import DiscoveredVideo, SourceReport
from thoth_control_plane.attribution.matching import TextBox
from thoth_control_plane.attribution.models import Platform

VisualKind = Literal["footage", "commentary", "unknown"]


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


class TextReader(Protocol):
    async def read(self, frame: Frame) -> list[TextBox]: ...


class VisionReader(Protocol):
    async def read_cover(self, frames: Sequence[Frame]) -> CoverReading | None: ...

    async def classify(self, frames: Sequence[Frame]) -> VisualKind | None: ...


class DecisionModel(Protocol):
    async def decide(
        self, evidence: dict[str, object], handles: Sequence[str]
    ) -> Decisions | None: ...


class Discoverer(Protocol):
    def supports(self, platform: Platform) -> bool: ...

    async def discover(self, platform: Platform, handle: str) -> list[DiscoveredVideo]: ...


class CandidateAcquirer(Protocol):
    async def acquire(self, candidate_id: str, url: str) -> AcquiredCandidate | None: ...

    async def discard(self, candidate_id: str) -> None: ...
