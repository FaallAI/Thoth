"""Footage domain types (spec 2026-10-14): objects, candidates, decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, get_args

from pydantic import Field

from thoth_control_plane.acquisition.models import DiscoveredVideo
from thoth_control_plane.domain.models import StrictModel

FootagePlatform = Literal["tiktok", "youtube", "x"]
CandidatePlatform = Literal["tiktok", "youtube", "x", "instagram"]
FootageStatus = Literal["ok", "none", "disabled", "unavailable"]
RejectReason = Literal[
    "main",
    "aggregator",
    "spam",
    "reaction_text",
    "duration",
    "story",
    "subtitle",
    "commentary",
    "object_absent",
    "duplicate",
    "media_failed",
    "vision_unavailable",
]
REJECT_REASONS: frozenset[str] = frozenset(get_args(RejectReason))


class FootageObject(StrictModel):
    """One search: the Indonesian query and the English look vision checks against."""

    query: Annotated[str, Field(min_length=1, max_length=100)]
    visual: Annotated[str, Field(min_length=1, max_length=300)]
    person: bool = False


@dataclass(frozen=True)
class NewCandidate:
    url: str
    platform: str
    source: str
    query: str
    visual: str
    owner_handle: str
    caption: str = ""
    published_at: str | None = None
    engagement: dict[str, int] = field(default_factory=dict)
    source_duration: float | None = None
    status: str = "pending"
    reason: str | None = None


@dataclass(frozen=True)
class CandidateView:
    url: str
    platform: str
    source: str
    query: str
    visual: str
    owner_handle: str
    caption: str
    published_at: str | None
    engagement: dict[str, int]
    source_duration: float | None
    status: str
    reason: str | None
    story_score: float | None
    kind: str | None
    shows_object: str | None
    description: str | None
    media_location: str | None
    media_checksum: str | None
    media_bytes: int | None
    clip_duration: float | None
    clip_start: float | None
    ocr: dict[str, Any] | None
    position: int | None


@dataclass(frozen=True)
class RunView:
    workflow_id: str
    status: str
    footage_status: str | None
    objects: list[FootageObject]


@dataclass(frozen=True)
class AdmittedClip:
    kind: str
    shows_object: str
    description: str
    media_location: str
    media_checksum: str
    media_bytes: int
    clip_duration: float
    clip_start: float
    ocr: dict[str, Any]
    position: int


@dataclass(frozen=True)
class FootageResult:
    status: FootageStatus
    admitted: int = 0
    rejected: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchBatch:
    """One platform's answers for a run's queries. `found` holds only queries the platform
    answered (an empty list is an answer); `failed` means it stopped or refused."""

    found: dict[str, list[DiscoveredVideo]]
    failed: bool
