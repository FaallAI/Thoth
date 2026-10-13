"""What Thoth decided about a post's origin, with the evidence it cites.

The artifact holds handles, public post URLs, bounded prose, and counts. It never holds a CDN
URL, a cookie, a proxy, a prompt, or raw model output.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, HttpUrl, model_validator

from thoth_control_plane.domain.models import OpaqueId, StrictModel

Platform = Literal["tiktok", "threads", "instagram", "x", "youtube"]
Verdict = Literal["original", "replaced", "unresolved"]
EvidenceKind = Literal[
    "caption", "frame_text", "cover_vision", "text_rule", "decision", "visual_match", "reaction"
]
Handle = Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,64}$")]
ReasonCode = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
MAX_EVIDENCE = 50


class AttributionEvidence(StrictModel):
    kind: EvidenceKind
    detail: Annotated[str, Field(min_length=1, max_length=300)]
    confidence: Annotated[float, Field(ge=0, le=1)] | None = None


class AttributedPost(StrictModel):
    platform: Platform
    canonical_url: HttpUrl
    owner_handle: Handle


class SourceAttribution(StrictModel):
    schema_version: Literal[1] = 1
    workflow_id: OpaqueId
    input: AttributedPost
    verdict: Verdict
    source: AttributedPost | None = None
    confidence: Literal["high", "low"] = "low"
    reason: ReasonCode | None = None
    evidence: list[AttributionEvidence] = Field(default_factory=list, max_length=MAX_EVIDENCE)
    candidates: dict[ReasonCode, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def source_exactly_when_replaced(self) -> SourceAttribution:
        if (self.verdict == "replaced") != (self.source is not None):
            raise ValueError("a source is present exactly when the verdict is replaced")
        return self
