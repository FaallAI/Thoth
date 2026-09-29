"""Strict, serializable acquisition contracts: single-post reports and TikTok discovery."""

from __future__ import annotations

import unicodedata
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    Field,
    HttpUrl,
    SecretStr,
    StringConstraints,
    model_validator,
)

from thoth_control_plane.domain.models import Checksum, OpaqueId, StrictModel

MAX_COMMENTS = 50
MAX_CARD_BYTES = 2 * 1024 * 1024


def _safe_relative_location(location: PurePosixPath) -> PurePosixPath:
    if location.is_absolute() or ".." in location.parts:
        raise ValueError("artifact location must be a safe relative path")
    return location


SafeRelativeLocation = Annotated[PurePosixPath, AfterValidator(_safe_relative_location)]
TikTokNumericId = Annotated[str, Field(pattern=r"^[0-9]{5,32}$")]
TikTokHandle = Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,64}$")]
CommentText = Annotated[str, Field(min_length=1, max_length=2_000)]
# The only shape `normalize.published_at_from_epoch` produces.
PublishedAt = Annotated[
    str, Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
]

MAX_MEDIA_ITEMS = 20
MAX_POST_TEXT = 50_000
SafeId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
MediaKind = Literal["video", "image"]
MediaType = Literal["video/mp4", "image/jpeg", "image/png", "image/webp"]
MEDIA_TYPES: dict[str, frozenset[str]] = {
    "video": frozenset({"video/mp4"}),
    "image": frozenset({"image/jpeg", "image/png", "image/webp"}),
}
MEDIA_BYTE_BOUNDS: dict[str, tuple[int, int]] = {
    "video": (10_000, 500 * 1024 * 1024),
    "image": (1_000, 20 * 1024 * 1024),
}


class AcquisitionStrategy(StrEnum):
    SCRAPLING_HEADLESS = "scrapling_headless"
    SCRAPLING_REQUEST = "scrapling_request"
    TIKWM_CDN = "tikwm_cdn"


class AttemptStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INCOMPLETE = "incomplete"


class AcquisitionReason(StrEnum):
    HEADLESS_TIMEOUT = "headless_timeout"
    HEADLESS_BLOCKED = "headless_blocked"
    HEADLESS_INCOMPLETE = "headless_incomplete"
    REQUEST_TIMEOUT = "request_timeout"
    REQUEST_BLOCKED = "request_blocked"
    REQUEST_INCOMPLETE = "request_incomplete"
    CDN_RATE_LIMITED = "cdn_rate_limited"
    CDN_UNAVAILABLE = "cdn_unavailable"
    MEDIA_VALIDATION_FAILED = "media_validation_failed"


class AcquisitionAttempt(StrictModel):
    strategy: AcquisitionStrategy
    status: AttemptStatus
    reason: AcquisitionReason | None = None
    attempt_count: Annotated[int, Field(ge=1, le=3)]
    elapsed_ms: Annotated[int, Field(ge=0)]


class TikTokPost(StrictModel):
    post_id: Annotated[str, Field(pattern=r"^[0-9]{5,32}$")]
    owner_handle: Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,64}$")]
    caption: Annotated[str, Field(max_length=10_000)] = ""
    published_at: PublishedAt | None = None
    engagement: dict[str, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)


class MediaRequestContext(StrictModel):
    """Browser session a signed media URL is bound to; never serialized or persisted."""

    user_agent: str | None = None
    referer: str
    # (cookie domain, name, value); a leading "." domain also matches subdomains.
    cookies: list[tuple[str, str, SecretStr]] = Field(default_factory=list, repr=False)


class ResolvedMedia(StrictModel):
    kind: MediaKind = "video"
    ephemeral_url: SecretStr = Field(exclude=True, repr=False)
    # Images carry None: the materializer's magic-byte sniff decides their type.
    media_type: Literal["video/mp4"] | None = "video/mp4"
    duration_seconds: Annotated[float, Field(ge=0)] | None = None
    request_context: MediaRequestContext | None = Field(default=None, exclude=True, repr=False)


class MaterializedMedia(StrictModel):
    media_id: OpaqueId
    kind: MediaKind = "video"
    index: Annotated[int, Field(ge=1, le=MAX_MEDIA_ITEMS)] = 1
    location: SafeRelativeLocation
    media_type: MediaType = "video/mp4"
    bytes: Annotated[int, Field(ge=1_000, le=524_288_000)]
    checksum: Checksum
    acquisition_strategy: AcquisitionStrategy
    width: Annotated[int, Field(gt=0)] | None = None
    height: Annotated[int, Field(gt=0)] | None = None
    duration_seconds: Annotated[float, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def match_kind(self) -> MaterializedMedia:
        low, high = MEDIA_BYTE_BOUNDS[self.kind]
        if self.media_type not in MEDIA_TYPES[self.kind] or not low <= self.bytes <= high:
            raise ValueError("media type and size must match the media kind")
        return self


class TikTokComment(StrictModel):
    comment_id: TikTokNumericId
    author: TikTokHandle
    text: CommentText
    likes: Annotated[int, Field(ge=0)] = 0
    # Real TikTok card crop (PNG); never a synthetic render, never serialized.
    card_png: bytes | None = Field(default=None, exclude=True, repr=False)


class BrowserSnapshot(StrictModel):
    final_url: HttpUrl
    post_candidates: list[TikTokPost] = Field(default_factory=list)
    media_candidates: list[ResolvedMedia] = Field(default_factory=list)
    comments: list[TikTokComment] = Field(default_factory=list)
    profile_card_png: bytes | None = Field(default=None, exclude=True, repr=False)


class TikTokSource(StrictModel):
    platform: Literal["tiktok"] = "tiktok"
    canonical_url: HttpUrl


class AcquisitionOutcome(StrictModel):
    status: Literal["resolved"] = "resolved"
    attempts: Annotated[list[AcquisitionAttempt], Field(min_length=1, max_length=3)]


class CardArtifact(StrictModel):
    """A real TikTok card crop persisted beside the report; never a synthetic render."""

    location: SafeRelativeLocation
    media_type: Literal["image/png"] = "image/png"
    bytes: Annotated[int, Field(ge=1, le=MAX_CARD_BYTES)]
    checksum: Checksum
    width: Annotated[int, Field(gt=0)]
    height: Annotated[int, Field(gt=0)]


class ReportComment(StrictModel):
    comment_id: TikTokNumericId
    author: TikTokHandle
    text: CommentText
    likes: Annotated[int, Field(ge=0)] = 0
    card: CardArtifact | None = None


class TikTokSourceReport(StrictModel):
    # Version 1 reports (Stage 1 evidence) carry no comments or cards and still validate.
    schema_version: Literal[1, 2] = 2
    workflow_id: OpaqueId
    source: TikTokSource
    post: TikTokPost
    media: Annotated[list[MaterializedMedia], Field(min_length=1, max_length=1)]
    outcome: AcquisitionOutcome
    comments: list[ReportComment] = Field(default_factory=list, max_length=MAX_COMMENTS)
    profile_card: CardArtifact | None = None

    @model_validator(mode="after")
    def keep_v1_free_of_enrichment(self) -> TikTokSourceReport:
        if self.schema_version == 1 and (self.comments or self.profile_card is not None):
            raise ValueError("schema_version 1 reports carry no comments or cards")
        if any(item.kind != "video" or item.index != 1 for item in self.media):
            raise ValueError("schema_version 1 and 2 reports carry one video at index 1")
        return self


class SourcePost(StrictModel):
    post_id: SafeId
    owner_handle: TikTokHandle
    text: Annotated[str, Field(max_length=MAX_POST_TEXT)] = ""
    published_at: PublishedAt | None = None
    engagement: dict[str, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)


class ReportSource(StrictModel):
    platform: Literal["tiktok", "threads", "instagram"]
    canonical_url: HttpUrl


class SourceReport(StrictModel):
    """Platform-neutral report (schema 3): a text-only post carries an empty media list."""

    schema_version: Literal[3] = 3
    workflow_id: OpaqueId
    source: ReportSource
    post: SourcePost
    media: list[MaterializedMedia] = Field(default_factory=list, max_length=MAX_MEDIA_ITEMS)
    outcome: AcquisitionOutcome
    comments: list[ReportComment] = Field(default_factory=list, max_length=MAX_COMMENTS)
    post_card: CardArtifact | None = None
    profile_card: CardArtifact | None = None

    @model_validator(mode="after")
    def require_ordered_content(self) -> SourceReport:
        if [item.index for item in self.media] != list(range(1, len(self.media) + 1)):
            raise ValueError("media indexes must run 1..N in order")
        if not self.media and not self.post.text.strip():
            raise ValueError("a post needs text or media")
        return self


class AcquisitionFailure(StrictModel):
    code: Literal[
        "invalid_tiktok_url",
        "invalid_source_url",
        "unsupported_platform",
        "headless_timeout",
        "headless_blocked",
        "headless_incomplete",
        "request_timeout",
        "request_blocked",
        "request_incomplete",
        "cdn_rate_limited",
        "cdn_unavailable",
        "media_validation_failed",
        "no_content",
        "artifact_persistence_failed",
        "acquisition_dependency_unavailable",
    ]
    retryable: bool
    attempts: Annotated[list[AcquisitionAttempt], Field(max_length=3)] = Field(default_factory=list)


class AcquisitionResult(StrictModel):
    report: SourceReport | None = None
    failure: AcquisitionFailure | None = None

    @model_validator(mode="after")
    def require_exactly_one_outcome(self) -> AcquisitionResult:
        if (self.report is None) == (self.failure is None):
            raise ValueError("acquisition result requires exactly one outcome")
        return self


EngagementKey = Literal["play", "like", "comment", "share", "collect"]
DiscoveryKind = Literal["profile", "keyword", "trending"]
DiscoveryLimit = Annotated[int, Field(ge=1, le=100)]


def _search_query(value: str) -> str:
    if not value or any(unicodedata.category(char) == "Cc" for char in value):
        raise ValueError("search query must be non-blank text without control characters")
    return value


# Stripped before the length check, so padding never counts against the 100 characters.
SearchQuery = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
    AfterValidator(_search_query),
]


class DiscoveryReason(StrEnum):
    CAPTCHA = "captcha"  # empty/non-JSON API body or captcha container rendered
    BLOCKED = "blocked"  # API JSON with a non-zero status code
    NO_DATA = "no_data"  # no matching API response was captured
    TIMEOUT = "timeout"  # navigation or the scroll deadline expired
    BROWSER_UNAVAILABLE = "browser_unavailable"  # the Scrapling stack could not start


class ProfileDiscovery(StrictModel):
    kind: Literal["profile"] = "profile"
    handle: TikTokHandle
    limit: DiscoveryLimit = 30


class KeywordDiscovery(StrictModel):
    kind: Literal["keyword"] = "keyword"
    query: SearchQuery
    limit: DiscoveryLimit = 30


class TrendingDiscovery(StrictModel):
    kind: Literal["trending"] = "trending"
    limit: DiscoveryLimit = 30


DiscoveryRequest = Annotated[
    ProfileDiscovery | KeywordDiscovery | TrendingDiscovery, Field(discriminator="kind")
]


class DiscoveredVideo(StrictModel):
    post_id: TikTokNumericId
    owner_handle: TikTokHandle
    canonical_url: HttpUrl  # rebuilt from handle and id, never taken from TikTok
    caption: Annotated[str, Field(max_length=10_000)] = ""
    published_at: PublishedAt | None = None
    duration_seconds: Annotated[float, Field(ge=0)] | None = None
    engagement: dict[EngagementKey, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)
    hashtags: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list
    )


class DiscoveryDrops(StrictModel):
    ads: Annotated[int, Field(ge=0)] = 0
    photo_posts: Annotated[int, Field(ge=0)] = 0
    # Missing/invalid id or handle, or a failed model validation.
    invalid: Annotated[int, Field(ge=0)] = 0


class DiscoveryResult(StrictModel):
    """A result with `reason` set and non-empty `videos` is a valid partial result."""

    kind: DiscoveryKind
    videos: list[DiscoveredVideo]  # deduplicated by post_id, first seen wins, at most limit
    pages: Annotated[int, Field(ge=0)]
    exhausted: bool  # the last captured page reported no more results
    drops: DiscoveryDrops
    reason: DiscoveryReason | None = None
