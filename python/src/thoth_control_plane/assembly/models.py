"""The Content Set: what a video is made from, typed and checksummed (schema 1).

It holds public post URLs, handles, bounded text, counts, and media locations relative to the
artifact root. Never a CDN URL, a cookie, a proxy, a prompt, or raw model output. The rules of
Scout's content-set lint (`scout/lib/validate.ts`) are validators here, so an invalid Content
Set cannot be built.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, HttpUrl, model_validator

from thoth_control_plane.acquisition.models import (
    CommentText,
    MediaType,
    PublishedAt,
    SafeRelativeLocation,
    TikTokHandle,
)
from thoth_control_plane.domain.models import Checksum, OpaqueId, StrictModel

MAX_COMMENTS = 12
MAX_FIGURES = 5
MAX_FOOTAGE = 6
FootageStatus = Literal["ok", "none", "disabled", "unavailable"]
OCR_ANALYZER_VERSION = "subtitle-classifier-v1"
EDGE = 1e-9  # envelope clamping can land a hair past 1.0
Platform = Literal["tiktok", "threads", "instagram", "x", "youtube"]
Seconds = Annotated[float, Field(ge=0)]
Fraction = Annotated[float, Field(ge=0, le=1)]
Extent = Annotated[float, Field(gt=0, le=1)]


class MediaRef(StrictModel):
    location: SafeRelativeLocation
    media_type: MediaType
    checksum: Checksum
    bytes: Annotated[int, Field(ge=1)]
    width: Annotated[int, Field(gt=0)] | None = None
    height: Annotated[int, Field(gt=0)] | None = None
    duration_seconds: Seconds | None = None


class BlurRegion(StrictModel):
    x: Fraction
    y: Fraction
    w: Extent
    h: Extent
    start: Seconds | None = None
    end: Seconds | None = None

    @model_validator(mode="after")
    def inside_and_ordered(self) -> BlurRegion:
        if self.x + self.w > 1 + EDGE or self.y + self.h > 1 + EDGE:
            raise ValueError("a blur region must stay inside the frame")
        if (self.start is None) != (self.end is None):
            raise ValueError("a blur window needs both start and end")
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError("a blur window must not end before it starts")
        return self


class MainOcr(StrictModel):
    schema_version: Literal[1] = 1
    engine: Literal["rapidocr"] = "rapidocr"
    analyzer_version: Literal["subtitle-classifier-v1"] = OCR_ANALYZER_VERSION
    analyzed_at: AwareDatetime
    requested_frames: Annotated[int, Field(gt=0)]
    valid_frames: Annotated[int, Field(gt=0)]
    # `overlay` (amendment 2026-10-12): a persistent added band, blurred with the audio kept.
    outcome: Literal["clean", "cover", "subtitle", "overlay"]
    trim_start: Seconds
    mute_audio: bool
    subtitle_blur: list[BlurRegion] = Field(default_factory=list, max_length=200)
    # True when the region comparison moved the trim off the classifier's sample midpoint.
    trim_refined: bool = False

    @model_validator(mode="after")
    def consistent(self) -> MainOcr:
        if self.valid_frames != self.requested_frames:
            raise ValueError("OCR coverage must be complete")
        if self.outcome == "clean" and (self.trim_start or self.mute_audio or self.subtitle_blur):
            raise ValueError("a clean verdict carries no trim, mute, or blur")
        if self.outcome == "cover" and (
            self.trim_start <= 0 or self.mute_audio or self.subtitle_blur
        ):
            raise ValueError("a cover verdict trims and carries no mute or blur")
        if self.outcome == "subtitle" and (not self.mute_audio or not self.subtitle_blur):
            raise ValueError("a subtitle verdict mutes and blurs")
        if self.outcome == "overlay" and (self.mute_audio or not self.subtitle_blur):
            raise ValueError("an overlay verdict blurs and keeps the audio")
        return self


class Main(StrictModel):
    source: Literal["input", "original"]
    url: HttpUrl
    platform: Platform
    title: Annotated[str, Field(max_length=120)] = ""
    description: Annotated[str, Field(max_length=50_000)] = ""
    owner_handle: TikTokHandle
    published_at: PublishedAt | None = None
    engagement: dict[str, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)
    kind: Literal["video", "images", "card"]
    video: MediaRef | None = None
    images: list[MediaRef] = Field(default_factory=list, max_length=20)
    card: MediaRef | None = None
    profile_card: MediaRef | None = None
    ocr: MainOcr | None = None

    @model_validator(mode="after")
    def media_matches_kind(self) -> Main:
        if (self.kind == "video") != (self.video is not None):
            raise ValueError("a video main has exactly one video")
        if (self.kind == "video") != (self.ocr is not None):
            raise ValueError("a video main needs its OCR, and only a video main has one")
        if (self.kind == "images") != bool(self.images):
            raise ValueError("an images main has at least one image")
        if (self.kind == "card") != (self.card is not None):
            raise ValueError("a card main has its post card")
        if self.video is not None and self.video.media_type != "video/mp4":
            raise ValueError("the main video must be video/mp4")
        if any(image.media_type == "video/mp4" for image in self.images):
            raise ValueError("main images must be images")
        return self


class Comment(StrictModel):
    text: CommentText
    author: TikTokHandle
    likes: Annotated[int, Field(ge=0)] = 0
    source: Literal["input", "original"]
    card: MediaRef | None = None  # a real card crop or nothing, never a synthetic render


class Figure(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    type: Literal["person", "organization", "community"]
    role: Annotated[str, Field(max_length=200)] = ""
    description: Annotated[str, Field(max_length=300)] = ""


class Footage(StrictModel):
    """One b-roll clip (spec 2026-10-14, section 6): a window file and its checks."""

    source: Literal["search", "carousel"]
    url: HttpUrl
    platform: Literal["tiktok", "youtube", "x", "instagram"]
    owner_handle: TikTokHandle
    published_at: PublishedAt | None = None
    engagement: dict[str, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)
    query: Annotated[str, Field(min_length=1, max_length=100)]
    visual: Annotated[str, Field(max_length=300)] = ""
    caption: Annotated[str, Field(max_length=2_000)] = ""
    description: Annotated[str, Field(max_length=300)] = ""
    video: MediaRef
    clip_start: Seconds = 0.0
    ocr: MainOcr
    story_score: Fraction
    shows_object: Literal["yes", "partly"]

    @model_validator(mode="after")
    def renderable(self) -> Footage:
        if self.video.media_type != "video/mp4":
            raise ValueError("footage must be video/mp4")
        if self.ocr.outcome == "subtitle":
            raise ValueError("the renderer refuses subtitle-classified footage")
        return self


class ContentSet(StrictModel):
    schema_version: Literal[1] = 1
    workflow_id: OpaqueId
    attribution_verdict: Literal["original", "replaced", "unresolved", "none"]
    main: Main
    comments: list[Comment] = Field(default_factory=list, max_length=MAX_COMMENTS)
    figures: list[Figure] = Field(default_factory=list, max_length=MAX_FIGURES)
    figures_status: Literal["ok", "none", "unavailable"]
    footage: list[Footage] = Field(default_factory=list, max_length=MAX_FOOTAGE)
    footage_status: FootageStatus = "disabled"

    @model_validator(mode="after")
    def consistent(self) -> ContentSet:
        if (self.figures_status == "ok") != bool(self.figures):
            raise ValueError("figures_status is ok exactly when figures are present")
        if (self.footage_status == "ok") != bool(self.footage):
            raise ValueError("footage_status is ok exactly when footage is present")
        urls = [str(item.url) for item in self.footage]
        if len(set(urls)) != len(urls) or str(self.main.url) in urls:
            raise ValueError("footage URLs are unique and never the main's")
        return self
